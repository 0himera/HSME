import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx
from openai import AsyncOpenAI
from pydantic import ValidationError

from backend.core.nlp_schemas import validate_nlp_extraction
from backend.core.prompts import load_prompt
from backend.core.config import (
    resolve_llm_settings,
    YANDEX_API_KEY,
    YANDEX_BASE_URL,
    YANDEX_FOLDER_ID,
    YANDEX_GPT_MODEL_120B,
    GEMINI_API_KEY,
)

logger = logging.getLogger(__name__)
DEFAULT_YANDEX_BASE_URL = YANDEX_BASE_URL
JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
MODERATION_REFUSAL_RE = re.compile(
    r"я\s+не\s+могу\s+обсуждать|can't\s+discuss|cannot\s+discuss",
    re.IGNORECASE,
)


class ModerationRefusalError(Exception):
    """Raised when the LLM returns a safety refusal instead of JSON."""


def is_moderation_refusal(text: str) -> bool:
    return bool(MODERATION_REFUSAL_RE.search(text.strip()))


def normalize_message_content(content: Any) -> str:
    """Normalize OpenAI-compatible message content to plain text."""
    if content is None:
        return ""
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or part.get("content") or ""))
            else:
                parts.append(str(part))
        return "".join(parts).strip()
    return str(content).strip()


def extract_json_payload(text: str) -> str:
    """Extract a JSON object string from model output or markdown fences."""
    clean = text.strip()
    if not clean:
        return ""

    fence_match = JSON_FENCE_PATTERN.search(clean)
    if fence_match:
        clean = fence_match.group(1).strip()

    start_idx = clean.find("{")
    end_idx = clean.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        return clean[start_idx : end_idx + 1]
    return clean


def uses_yandex_json_mode(model_id: str, *, use_gemini: bool) -> bool:
    return not use_gemini and model_id.startswith("gpt://")


def repair_json_text(raw_json: str) -> str:
    """Apply lightweight fixes for common LLM JSON formatting mistakes."""
    repaired = raw_json.replace("\ufeff", "")
    repaired = repaired.replace("“", '"').replace("”", '"')
    repaired = repaired.replace("‘", "'").replace("’", "'")
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    return repaired


def parse_llm_json(raw_json: str) -> dict[str, Any]:
    """Parse LLM JSON payload, tolerating control chars and minor formatting issues."""
    candidates = (raw_json, repair_json_text(raw_json))
    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        if not candidate:
            continue
        try:
            payload = json.loads(candidate, strict=False)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if not isinstance(payload, dict):
            raise ValueError("Model JSON root must be an object")
        return payload
    if last_error is not None:
        raise last_error
    raise json.JSONDecodeError("Expecting value", raw_json, 0)


class GeminiCompletions:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def create(self, model=None, messages=None, temperature=0.1, max_tokens=1000, **kwargs):
        system_instruction = None
        contents = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                system_instruction = content
            else:
                gemini_role = "model" if role in ["assistant", "model"] else "user"
                contents.append({
                    "role": gemini_role,
                    "parts": [{"text": content}]
                })

        if not contents:
            contents.append({
                "role": "user",
                "parts": [{"text": "Process request."}]
            })

        gemini_max_tokens = max(max_tokens, 2048) if max_tokens else 2048

        body = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": gemini_max_tokens
            }
        }
        if system_instruction:
            body["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent"
        headers = {
            "Content-Type": "application/json",
            "X-goog-api-key": self.api_key
        }

        async with httpx.AsyncClient() as client:
            res = await client.post(url, json=body, headers=headers, timeout=60.0)
            res.raise_for_status()
            data = res.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]

        class MockMessage:
            def __init__(self, content):
                self.content = content

        class MockChoice:
            def __init__(self, content):
                self.message = MockMessage(content)

        class MockResponse:
            def __init__(self, content):
                self.choices = [MockChoice(content)]

        return MockResponse(text)


class GeminiChatCompletions:
    def __init__(self, api_key: str):
        self.completions = GeminiCompletions(api_key)


class GeminiClient:
    def __init__(self, api_key: str):
        self.chat = GeminiChatCompletions(api_key)


def _default_llm_params() -> dict[str, Optional[str]]:
    settings = resolve_llm_settings()
    api_key = settings.get("LLM_API_KEY") or YANDEX_API_KEY or ""
    folder_id = settings.get("LLM_FOLDER_ID") or YANDEX_FOLDER_ID or ""
    model_id = settings.get("LLM_MODEL_ID") or (YANDEX_GPT_MODEL_120B if folder_id else None)
    is_yandex = bool(folder_id) or (model_id and model_id.startswith("gpt://"))
    if is_yandex:
        base_url = YANDEX_BASE_URL
    else:
        base_url = settings.get("LLM_BASE_URL") or DEFAULT_YANDEX_BASE_URL
    return {
        "api_key": api_key,
        "folder_id": folder_id,
        "base_url": base_url,
        "model_id": model_id,
    }


class NLPExtractor:
    def __init__(
        self,
        api_key: Optional[str] = None,
        folder_id: Optional[str] = None,
        base_url: Optional[str] = None,
        model_id: Optional[str] = None,
    ):
        defaults = _default_llm_params()
        resolved_api_key = api_key if api_key is not None else defaults["api_key"]
        resolved_folder_id = folder_id if folder_id is not None else defaults["folder_id"]
        resolved_base_url = base_url if base_url is not None else defaults["base_url"]
        resolved_model_id = model_id if model_id is not None else defaults["model_id"]

        if resolved_api_key and resolved_api_key not in ("", "your_yandex_api_key_here"):
            self.client = AsyncOpenAI(
                api_key=resolved_api_key,
                base_url=resolved_base_url,
                project=resolved_folder_id or None,
            )
            if resolved_model_id:
                self.model_id = resolved_model_id
            elif resolved_folder_id:
                self.model_id = f"gpt://{resolved_folder_id}/gpt-oss-120b/latest"
            else:
                self.model_id = "gpt://placeholder/gpt-oss-120b/latest"
            self._use_gemini = False
        elif GEMINI_API_KEY:
            self.client = GeminiClient(api_key=GEMINI_API_KEY)
            self.model_id = "gemini-3.1-flash-lite"
            self._use_gemini = True
        else:
            self.client = AsyncOpenAI(
                api_key=resolved_api_key,
                base_url=resolved_base_url,
                project=resolved_folder_id or None,
            )
            self.model_id = resolved_model_id or "gpt://placeholder/gpt-oss-120b/latest"
            self._use_gemini = False

    async def extract_entities_and_relations(self, chunk_text: str) -> Dict[str, Any]:
        """Asynchronously calls LLM to extract entities and relations from a text chunk."""
        prompt_config = load_prompt("nlp_extractor")
        system_prompt = prompt_config["system"]
        moderation_retry_prompt = prompt_config.get("system_moderation_retry", system_prompt)
        user_prompt = prompt_config["user"].format(chunk_text=chunk_text)

        use_moderation_prompt = False
        saw_moderation_refusal = False

        for attempt in range(3):
            try:
                current_system = moderation_retry_prompt if use_moderation_prompt else system_prompt
                request_kwargs: Dict[str, Any] = {
                    "model": self.model_id,
                    "messages": [
                        {"role": "system", "content": current_system},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 3000,
                }
                if uses_yandex_json_mode(self.model_id, use_gemini=self._use_gemini):
                    request_kwargs["response_format"] = {"type": "json_object"}
                if not self._use_gemini and not self.model_id.startswith("gpt://"):
                    request_kwargs["extra_headers"] = {
                        "HTTP-Referer": "https://github.com/lifefucky/HSME",
                        "X-Title": "HSME Ingestion Pipeline",
                    }

                response = await self.client.chat.completions.create(**request_kwargs)

                content = normalize_message_content(response.choices[0].message.content)
                if not content:
                    logger.warning(
                        "Extraction attempt %d returned empty content from model",
                        attempt + 1,
                    )
                    continue

                if is_moderation_refusal(content):
                    saw_moderation_refusal = True
                    use_moderation_prompt = True
                    logger.warning("moderation_refusal attempt=%d preview=%.200r", attempt + 1, content)
                    await asyncio.sleep(2 * (attempt + 1))
                    continue

                clean_json = extract_json_payload(content)
                if not clean_json:
                    logger.warning(
                        "Extraction attempt %d returned no JSON payload; preview=%.200r",
                        attempt + 1,
                        content,
                    )
                    continue

                parsed_data = validate_nlp_extraction(parse_llm_json(clean_json), strict=False)
                self._enrich_numeric_properties(chunk_text, parsed_data)
                return parsed_data
            except ValidationError as exc:
                logger.warning(
                    "Extraction attempt %d failed validation: %s; preview=%.200r",
                    attempt + 1,
                    exc.error_count(),
                    locals().get("clean_json", ""),
                )
                await asyncio.sleep(2 * (attempt + 1))
            except json.JSONDecodeError as exc:
                logger.warning(
                    "Extraction attempt %d failed: %s; preview=%.200r",
                    attempt + 1,
                    exc,
                    locals().get("clean_json", ""),
                )
                await asyncio.sleep(2 * (attempt + 1))
            except Exception as e:
                if "429" in str(e) or "Too Many Requests" in str(e):
                    retry_after = 5 * (attempt + 1)
                    if hasattr(e, "response") and e.response is not None:
                        header_val = e.response.headers.get("Retry-After")
                        if header_val and header_val.isdigit():
                            retry_after = max(int(header_val), retry_after)
                    logger.warning(
                        "Rate limited (429) on attempt %d. Retrying in %ds...",
                        attempt + 1,
                        retry_after,
                    )
                    await asyncio.sleep(retry_after)
                else:
                    logger.warning("Extraction attempt %d failed: %s", attempt + 1, e)
                    await asyncio.sleep(2 * (attempt + 1))

        if saw_moderation_refusal:
            return {"entities": [], "relations": [], "_skip_reason": "moderation"}
        return {"entities": [], "relations": [], "_skip_reason": "validation_failed"}

    def _enrich_numeric_properties(self, text: str, data: Dict[str, Any]):
        """Runs regex patterns over the text chunk to ensure important numerical parameters are not missed."""
        existing_values = {e["value"].lower() for e in data.get("entities", []) if e["type"] == "Property"}

        patterns = [
            (r'\b(\d+[-–]\d+\s*°C|\d+\s*°C|\d+\s*К)\b', "Property", "temperature"),
            (r'\b(pH\s*[:=]?\s*\d+([.,]\d+)?)\b', "Property", "pH"),
            (r'\b(\d+\s*А/м[²2]|\d+[-–]\d+\s*А/м[²2])\b', "Property", "current_density"),
            (r'\b(\d+([.,]\d+)?\s*(?:мг/л|мг/дм³|г/л|%|МПа|HB))\b', "Property", "value_range"),
            (r'\b(?:[<>]|≤|≥)\s*\d+([.,]\d+)?\s*(?:мг/л|мг/дм³|г/л|%|МПа|HB)\b', "Property", "threshold")
        ]

        for pattern, ent_type, label in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for m in matches:
                val = m[0] if isinstance(m, tuple) else m
                val_clean = val.strip()
                if val_clean.lower() not in existing_values:
                    data.setdefault("entities", []).append({
                        "type": ent_type,
                        "value": val_clean
                    })
                    existing_values.add(val_clean.lower())
