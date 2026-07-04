"""Query parsing for eval runners — deterministic local parse, optional async LLM."""

from __future__ import annotations

import asyncio
import re
from typing import List

from backend.core.models import Entity
from backend.routers.search import parse_query_to_entities


def _contains_term(text_lower: str, term: str) -> bool:
    t = term.lower()
    if t in text_lower:
        return True
    if len(t) > 4:
        stem = t[:-2]
        return stem in text_lower
    return False


def parse_query_local_sync(query_text: str) -> List[Entity]:
    """Regex-only NL parse (same heuristics as search.py fallback). No network."""
    entities: List[Entity] = []
    text_lower = query_text.lower()

    materials = ["никель", "медь", "электролит", "раствор", "руда", "шлак", "кобальт", "шлам", "штейн"]
    for mat in materials:
        if _contains_term(text_lower, mat):
            entities.append(
                Entity(
                    type="Material",
                    value=mat.capitalize() if mat not in ["никель", "медь"] else mat,
                )
            )
    if "медн" in text_lower and not any(e.value == "медь" for e in entities):
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
            entities.append(Entity(type="Property", value=ph_match2.group(1).upper().replace(" ", ": ")))

    temp_match = re.search(r"\b(\d+\s*°c)\b", text_lower)
    if temp_match:
        entities.append(Entity(type="Property", value=f"Температура: {temp_match.group(1).upper()}"))

    dens_match = re.search(r"\b(\d+\s*а/м2)\b", text_lower)
    if dens_match:
        entities.append(Entity(type="Property", value=f"плотность тока: {dens_match.group(1).upper()}"))

    return entities


async def parse_query_with_timeout(
    query_text: str,
    *,
    timeout_s: float = 15.0,
    prefer_local: bool = False,
) -> List[Entity]:
    if prefer_local:
        return parse_query_local_sync(query_text)
    try:
        return await asyncio.wait_for(
            parse_query_to_entities(query_text),
            timeout=timeout_s,
        )
    except (asyncio.TimeoutError, Exception):
        return parse_query_local_sync(query_text)


def parse_query_sync(
    query_text: str,
    *,
    timeout_s: float = 15.0,
    prefer_local: bool = True,
) -> List[Entity]:
    """Sync entry for retrieval runner; defaults to local regex (no nested event loop)."""
    if prefer_local:
        return parse_query_local_sync(query_text)
    return asyncio.run(parse_query_with_timeout(query_text, timeout_s=timeout_s, prefer_local=False))
