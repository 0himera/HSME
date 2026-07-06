"""Query parsing wrappers for eval runners — timeouts and sync entry points."""

from __future__ import annotations

import asyncio
from typing import List

from backend.core.models import Entity
from backend.services.query_parse import parse_query_local_sync, parse_query_to_entities

# Re-export for tests and backward compatibility
__all__ = [
    "parse_query_local_sync",
    "parse_query_to_entities",
    "parse_query_with_timeout",
    "parse_query_sync",
]


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
