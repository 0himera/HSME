"""L0 query parsing — shared by API search and eval runners."""

from __future__ import annotations

import json
import logging
import re
from typing import List

from backend.core.models import Entity
from backend.core.prompts import load_prompt
from backend.services.nlp_extractor import NLPExtractor

logger = logging.getLogger(__name__)


def _contains_term(text_lower: str, term: str) -> bool:
    t = term.lower()
    if t in text_lower:
        return True
    if len(t) > 4:
        stem = t[:-2]
        return stem in text_lower
    return False


def parse_query_local_sync(query_text: str) -> List[Entity]:
    """Regex-only NL parse. No network — canonical fallback for L0."""
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
            entities.append(
                Entity(
                    type="Material",
                    value=mat.capitalize() if mat not in ["никель", "медь"] else mat,
                )
            )
    if "медн" in text_lower or "меди" in text_lower:
        if not any(e.value == "медь" for e in entities):
            entities.append(Entity(type="Material", value="медь"))

    processes = [
        ("электроэкстракция", "Электроэкстракция"),
        ("выщелачивание", "Кучное выщелачивание"),
        ("обессоливание", "Обессоливание"),
    ]
    for p_kw, p_val in processes:
        if _contains_term(text_lower, p_kw):
            entities.append(Entity(type="Process", value=p_val))

    facilities = [
        ("кольская", "Кольская ГМК"),
        ("long harbour", "Завод Long Harbour"),
        ("кайеркан", "рудник Кайерканский"),
    ]
    for f_kw, f_val in facilities:
        if _contains_term(text_lower, f_kw):
            entities.append(Entity(type="Facility", value=f_val))

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


async def parse_query_to_entities(query_text: str) -> List[Entity]:
    """Parse NL query via LLM; fall back to regex heuristics on failure."""
    try:
        prompt_config = load_prompt("search_parse_query")
        system_prompt = prompt_config["system"]
        user_prompt = prompt_config["user"].format(query_text=query_text)

        extractor = NLPExtractor()
        response = await extractor.client.chat.completions.create(
            model=extractor.model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=300,
        )
        content = response.choices[0].message.content.strip()

        json_match = re.search(r"(\[\s*\{.*\}\s*\])", content, re.DOTALL)
        if json_match:
            content = json_match.group(1).strip()
        else:
            cb_match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
            if cb_match:
                content = cb_match.group(1).strip()
            else:
                if content.startswith("```json"):
                    content = content[7:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

        parsed = json.loads(content)
        entities: List[Entity] = []
        for item in parsed:
            t = item.get("type")
            v = item.get("value")
            if t and v:
                entities.append(Entity(type=t, value=v))
        if entities:
            return entities
    except Exception as exc:
        logger.warning("LLM query parse failed, using regex fallback: %s", exc)

    return parse_query_local_sync(query_text)
