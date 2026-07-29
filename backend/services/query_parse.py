"""L0 query parsing — shared by API search and eval runners."""

from __future__ import annotations

import json
import logging
import re
from typing import List, Sequence, Tuple

from pydantic import ValidationError

from backend.core.config import resolve_llm_settings
from backend.core.models import Entity
from backend.core.nlp_schemas import QueryParseResult
from backend.core.prompts import load_prompt
from backend.repository.database import db
from backend.services.embedding import (
    is_semantic_entity_key,
    normalize_entity_value,
)
from backend.services.nlp_extractor import (
    NLPExtractor,
    extract_json_payload,
    normalize_message_content,
    repair_json_text,
    uses_yandex_json_mode,
)

logger = logging.getLogger(__name__)

LOCAL_ENTITY_TYPES = (
    "Material",
    "Process",
    "Equipment",
    "Property",
    "Expert",
    "Publication",
    "Facility",
)


def _contains_term(text_lower: str, term: str) -> bool:
    t = term.lower()
    if t in text_lower:
        return True
    if len(t) > 4:
        stem = t[:-2]
        return stem in text_lower
    return False


def _normalize_query_text(query_text: str) -> str:
    return normalize_entity_value(query_text)


def _iter_codebook_entities() -> List[Tuple[str, str]]:
    candidates: List[Tuple[str, str]] = []
    for key in db.codebook.keys():
        if not is_semantic_entity_key(key):
            continue
        entity_type, value = key.split(":", 1)
        if entity_type in LOCAL_ENTITY_TYPES:
            candidates.append((entity_type, value))
    return sorted(candidates, key=lambda item: len(item[1]), reverse=True)


def _match_normalized_term(normalized_query: str, normalized_value: str) -> bool:
    if not normalized_value:
        return False
    if normalized_value in normalized_query:
        return True
    if _contains_term(normalized_query, normalized_value):
        return True
    tokens = normalized_value.split()
    if len(tokens) > 1:
        significant = [token for token in tokens if len(token) >= 3]
        if significant and all(_contains_term(normalized_query, token) for token in significant):
            return True
    if len(normalized_value) > 4:
        return normalized_value[:-2] in normalized_query
    return False


def _dedupe_entities(entities: Sequence[Entity]) -> List[Entity]:
    seen: set[str] = set()
    deduped: List[Entity] = []
    for entity in entities:
        key = entity.to_key()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entity)
    return deduped


def _extract_from_codebook(query_text: str) -> List[Entity]:
    normalized_query = _normalize_query_text(query_text)
    entities: List[Entity] = []
    for entity_type, value in _iter_codebook_entities():
        if _match_normalized_term(normalized_query, value):
            entities.append(Entity(type=entity_type, value=value))
    return entities


def _extract_properties_regex(query_text: str) -> List[Entity]:
    entities: List[Entity] = []
    text_lower = query_text.lower()

    ph_match = re.search(r"\b(ph\s*[:=<>≤≥]?\s*\d+([.,]\d+)?)\b", text_lower)
    if ph_match:
        entities.append(Entity(type="Property", value=ph_match.group(1).upper()))
    else:
        ph_match2 = re.search(r"\b(ph\s+\d+([.,]\d+)?)\b", text_lower)
        if ph_match2:
            entities.append(
                Entity(type="Property", value=ph_match2.group(1).upper().replace(" ", ": "))
            )

    temp_match = re.search(r"\b(\d+\s*°c)\b", text_lower)
    if temp_match:
        entities.append(Entity(type="Property", value=f"Температура: {temp_match.group(1).upper()}"))

    dens_match = re.search(r"\b(\d+\s*а/м2)\b", text_lower)
    if dens_match:
        entities.append(Entity(type="Property", value=f"плотность тока: {dens_match.group(1).upper()}"))

    return entities


def _legacy_hardcode_entities(query_text: str) -> List[Entity]:
    """Emergency fallback when semantic codebook is sparse."""
    entities: List[Entity] = []
    text_lower = query_text.lower()

    materials = [
        "никель",
        "медь",
        "электролит",
        "раствор",
        "руда",
        "шлак",
        "кобальт",
        "шлам",
        "штейн",
    ]
    for mat in materials:
        if _contains_term(text_lower, mat):
            entities.append(Entity(type="Material", value=mat))

    if "медн" in text_lower or "меди" in text_lower:
        if not any(e.value == "медь" for e in entities):
            entities.append(Entity(type="Material", value="медь"))

    processes = [
        ("электроэкстракция", "электроэкстракция"),
        ("выщелачивание", "кучное выщелачивание"),
        ("обессоливание", "обессоливание"),
    ]
    for p_kw, p_val in processes:
        if _contains_term(text_lower, p_kw):
            entities.append(Entity(type="Process", value=p_val))

    facilities = [
        ("кольская", "кольская гмк"),
        ("long harbour", "завод long harbour"),
        ("кайеркан", "рудник кайерканский"),
    ]
    for f_kw, f_val in facilities:
        if _contains_term(text_lower, f_kw):
            entities.append(Entity(type="Facility", value=f_val))

    return entities


def parse_query_local_sync(query_text: str) -> List[Entity]:
    """Regex/codebook NL parse. No network — canonical fallback for L0."""
    query_text = query_text.strip()
    if not query_text:
        return []

    entities = _extract_from_codebook(query_text)
    entities.extend(_extract_properties_regex(query_text))
    entities.extend(_legacy_hardcode_entities(query_text))

    return _dedupe_entities(entities)


def _openai_strict_json_schema(model: type[QueryParseResult]) -> dict:
    """Prepare a Pydantic JSON schema for OpenAI strict structured outputs."""

    def _enforce_strict(node: object) -> object:
        if not isinstance(node, dict):
            return node
        result = {key: _enforce_strict(value) for key, value in node.items()}
        if result.get("type") == "object":
            result["additionalProperties"] = False
            if "properties" in result and "required" not in result:
                result["required"] = list(result["properties"].keys())
        if result.get("type") == "array" and "items" in result:
            result["items"] = _enforce_strict(result["items"])
        return result

    return _enforce_strict(model.model_json_schema())


def _supports_json_schema(extractor: NLPExtractor) -> bool:
    if extractor._use_gemini or extractor.model_id.startswith("gpt://"):
        return False
    settings = resolve_llm_settings()
    base_url = (settings.get("LLM_BASE_URL") or "").lower()
    if "openrouter.ai" in base_url:
        return False
    return extractor.model_id.startswith("gpt-")


def _entities_from_parsed_payload(payload: object) -> List[Entity]:
    if isinstance(payload, list):
        result = QueryParseResult.model_validate({"entities": payload})
    elif isinstance(payload, dict):
        if "entities" in payload:
            result = QueryParseResult.model_validate(payload)
        else:
            result = QueryParseResult.model_validate({"entities": [payload]})
    else:
        raise ValidationError.from_exception_data(
            "QueryParseResult",
            [{"type": "value_error", "loc": (), "msg": "unsupported payload", "input": payload}],
        )
    return [Entity(type=item.type, value=item.value) for item in result.entities]


def _parse_query_content(content: str) -> List[Entity]:
    clean = content.strip()
    if not clean:
        return []

    array_match = re.search(r"(\[\s*\{.*\}\s*\])", clean, re.DOTALL)
    if array_match:
        payload = json.loads(repair_json_text(array_match.group(1)))
        return _entities_from_parsed_payload(payload)

    json_payload = extract_json_payload(clean)
    if not json_payload:
        json_payload = repair_json_text(clean)

    try:
        payload = json.loads(json_payload)
    except json.JSONDecodeError:
        payload = json.loads(repair_json_text(json_payload))

    return _entities_from_parsed_payload(payload)


async def parse_query_to_entities(query_text: str) -> List[Entity]:
    """Parse NL query via LLM; fall back to local heuristics on failure."""
    try:
        prompt_config = load_prompt("search_parse_query")
        system_prompt = prompt_config["system"]
        user_prompt = prompt_config["user"].format(query_text=query_text)

        extractor = NLPExtractor()
        request_kwargs = {
            "model": extractor.model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 2500,
        }

        if _supports_json_schema(extractor):
            request_kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "query_parse_result",
                    "schema": _openai_strict_json_schema(QueryParseResult),
                    "strict": True,
                },
            }
        elif uses_yandex_json_mode(extractor.model_id, use_gemini=extractor._use_gemini):
            request_kwargs["response_format"] = {"type": "json_object"}

        response = await extractor.client.chat.completions.create(**request_kwargs)
        raw_content = response.choices[0].message.content
        if not raw_content:
            raw_content = getattr(response.choices[0].message, "reasoning_content", None) or ""
        content = normalize_message_content(raw_content)

        entities = _parse_query_content(content)
        if entities:
            return entities
    except Exception as exc:
        logger.warning("LLM query parse failed, using local fallback: %s", exc)

    return parse_query_local_sync(query_text)
