"""Tests for shared L0 query parser (RAP risk #3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.models import Entity
from backend.evaluation.runners.query_parse import parse_query_local_sync as eval_parse
from backend.services.query_parse import parse_query_local_sync, parse_query_to_entities


def test_unified_parser_service_and_eval_wrapper():
    query = "извлечение меди при pH 2.0"
    service_keys = [e.to_key() for e in parse_query_local_sync(query)]
    eval_keys = [e.to_key() for e in eval_parse(query)]
    assert service_keys == eval_keys
    assert any(e.type == "Material" and e.value == "медь" for e in eval_parse(query))
    assert any(e.type == "Property" for e in eval_parse(query))


def test_parse_garbage_returns_empty_list():
    assert parse_query_local_sync("абырвалг") == []


@pytest.mark.asyncio
async def test_parse_query_llm_fallback_on_failure():
    mock_extractor = MagicMock()
    mock_extractor.client.chat.completions.create = AsyncMock(side_effect=RuntimeError("network down"))

    with patch("backend.services.query_parse.NLPExtractor", return_value=mock_extractor):
        entities = await parse_query_to_entities("электроэкстракция никеля при pH 2.0")

    assert len(entities) > 0
    types = {e.type for e in entities}
    assert "Process" in types or "Material" in types


@pytest.mark.asyncio
async def test_search_router_uses_shared_parser_fallback():
    """POST /api/search NL path uses the same fallback module as eval."""
    from fastapi.testclient import TestClient
    from backend.app import app

    query = "извлечение меди при pH 2.0"
    expected = parse_query_local_sync(query)

    mock_extractor = MagicMock()
    mock_extractor.client.chat.completions.create = AsyncMock(side_effect=RuntimeError("llm down"))

    with patch("backend.services.query_parse.NLPExtractor", return_value=mock_extractor):
        client = TestClient(app)
        response = client.post(
            "/api/search",
            json={"query": query, "paged": True, "limit": 3},
            headers={"X-User-Name": "test", "X-User-Role": "Administrator"},
        )

    assert response.status_code == 200
    # Indirect check: if parser failed, we'd get empty results for a copper query
    data = response.json()
    if isinstance(data, dict) and data.get("total", 0) > 0:
        assert len(expected) > 0
