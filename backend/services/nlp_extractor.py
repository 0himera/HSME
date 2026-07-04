import json
import re
import asyncio
import logging
from typing import List, Dict, Any, Optional

import httpx
from openai import AsyncOpenAI

from backend.core.prompts import load_prompt
from backend.core.config import (
    resolve_llm_settings,
    YANDEX_API_KEY,
    YANDEX_FOLDER_ID,
    YANDEX_GPT_MODEL_120B,
    GEMINI_API_KEY,
)

logger = logging.getLogger(__name__)
DEFAULT_BASE_URL = "https://ai.api.cloud.yandex.net/v1"


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
    
    # If no LLM_API_KEY is resolved (or is empty), fall back to Yandex settings entirely
    if not settings.get("LLM_API_KEY"):
        api_key = YANDEX_API_KEY or ""
        folder_id = YANDEX_FOLDER_ID or ""
        base_url = DEFAULT_BASE_URL
        model_id = YANDEX_GPT_MODEL_120B if folder_id else None
    else:
        api_key = settings.get("LLM_API_KEY")
        folder_id = settings.get("LLM_FOLDER_ID") or YANDEX_FOLDER_ID or ""
        base_url = settings.get("LLM_BASE_URL") or DEFAULT_BASE_URL
        model_id = settings.get("LLM_MODEL_ID") or (YANDEX_GPT_MODEL_120B if folder_id else None)
        
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
            if resolved_api_key:
                self.client = AsyncOpenAI(
                    api_key=resolved_api_key,
                    base_url=resolved_base_url,
                    project=resolved_folder_id or None,
                )
            else:
                self.client = None
            self.model_id = resolved_model_id or "gpt://placeholder/gpt-oss-120b/latest"
            self._use_gemini = False

    async def extract_entities_and_relations(self, chunk_text: str) -> Dict[str, Any]:
        """Asynchronously calls LLM to extract entities and relations from a text chunk."""
        if not self.client:
            logger.warning("LLM client not initialized (missing API key). Using regex fallback.")
            parsed_data: Dict[str, Any] = {"entities": [], "relations": []}
            self._enrich_numeric_properties(chunk_text, parsed_data)
            return parsed_data

        prompt_config = load_prompt("nlp_extractor")
        system_prompt = prompt_config["system"]
        user_prompt = prompt_config["user"].format(chunk_text=chunk_text)

        for attempt in range(3):
            try:
                request_kwargs: Dict[str, Any] = {
                    "model": self.model_id,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 3000,
                }
                if not self._use_gemini:
                    request_kwargs["extra_headers"] = {
                        "HTTP-Referer": "https://github.com/lifefucky/HSME",
                        "X-Title": "HSME Ingestion Pipeline",
                    }

                response = await self.client.chat.completions.create(**request_kwargs)

                content = response.choices[0].message.content
                if not content:
                    continue

                clean_json = content.strip()
                start_idx = clean_json.find('{')
                end_idx = clean_json.rfind('}')
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    clean_json = clean_json[start_idx:end_idx + 1]

                parsed_data = json.loads(clean_json)
                self._enrich_numeric_properties(chunk_text, parsed_data)
                return parsed_data
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

        return {"entities": [], "relations": []}

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
