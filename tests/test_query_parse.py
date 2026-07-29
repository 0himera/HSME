"""Tests for shared L0 query parser (RAP risk #3 + Stage 2c)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.models import Entity
from backend.core.nlp_schemas import QueryParseResult
from backend.evaluation.runners.query_parse import parse_query_local_sync as eval_parse
from backend.repository.database import db
from backend.repository.ontology_importer import import_ontology
from backend.services.embedding import EmbeddingService, normalize_entity_key
from backend.services.query_parse import (
    _parse_query_content,
    parse_query_local_sync,
    parse_query_to_entities,
)


def test_unified_parser_service_and_eval_wrapper():
    query = "извлечение меди при pH 2.0"
    service_keys = [e.to_key() for e in parse_query_local_sync(query)]
    eval_keys = [e.to_key() for e in eval_parse(query)]
    assert service_keys == eval_keys
    assert any(e.type == "Material" for e in eval_parse(query))
    assert any(e.type == "Property" for e in eval_parse(query))


def test_parse_garbage_returns_empty_list():
    assert parse_query_local_sync("абырвалг") == []
    assert parse_query_local_sync("") == []
    assert parse_query_local_sync("   ") == []


def test_parse_query_content_accepts_wrapped_entities():
    payload = {
        "entities": [
            {"type": "Material", "value": "никель"},
            {"type": "Process", "value": "электроэкстракция"},
        ]
    }
    entities = _parse_query_content(json.dumps(payload))
    assert len(entities) == 2
    assert entities[0].type == "Material"
    assert entities[0].value == "никель"


def test_parse_query_content_accepts_legacy_array_payload():
    payload = [{"type": "Material", "value": "медь"}]
    entities = _parse_query_content(json.dumps(payload))
    assert len(entities) == 1
    assert entities[0].to_key() == "Material:медь"


def test_query_parse_result_schema_validation():
    result = QueryParseResult.model_validate(
        {"entities": [{"type": "Facility", "value": "Long Harbour Plant"}]}
    )
    assert result.entities[0].type == "Facility"
    assert result.entities[0].value == "Long Harbour Plant"


def test_dynamic_codebook_extracts_seeded_facility():
    query = "Какие параметры используются на заводе Long Harbour?"
    entities = parse_query_local_sync(query)
    keys = {e.to_key() for e in entities}
    assert "Facility:завод long harbour" in keys


def test_dynamic_codebook_extracts_kayerkan_facility():
    query = "Что известно про рудник Кайерканский?"
    entities = parse_query_local_sync(query)
    assert any(e.type == "Facility" and "кайеркан" in e.value for e in entities)


def test_property_regex_still_extracts_ph_and_temperature():
    query = "Какие опыты с Температура: 45°C и pH: 2.0 проводились?"
    entities = parse_query_local_sync(query)
    assert any(e.type == "Property" and "PH" in e.value.upper() for e in entities)
    assert any(e.type == "Property" and "температура" in e.value.lower() for e in entities)


@pytest.mark.asyncio
async def test_parse_query_llm_fallback_on_failure():
    mock_extractor = MagicMock()
    mock_extractor.client.chat.completions.create = AsyncMock(side_effect=RuntimeError("network down"))
    mock_extractor.model_id = "gpt://folder/yandexgpt-5.1/latest"
    mock_extractor._use_gemini = False

    with patch("backend.services.query_parse.NLPExtractor", return_value=mock_extractor):
        entities = await parse_query_to_entities("электроэкстракция никеля при pH 2.0")

    assert len(entities) > 0
    types = {e.type for e in entities}
    assert "Process" in types or "Material" in types


@pytest.mark.asyncio
async def test_parse_query_llm_structured_output_success():
    mock_extractor = MagicMock()
    mock_extractor.model_id = "gpt-4o-mini"
    mock_extractor._use_gemini = False
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps(
                    {
                        "entities": [
                            {"type": "Process", "value": "обессоливание"},
                            {"type": "Facility", "value": "обогатительная фабрика"},
                        ]
                    }
                ),
                reasoning_content=None,
            )
        )
    ]
    mock_extractor.client.chat.completions.create = AsyncMock(return_value=mock_response)

    with patch("backend.services.query_parse.NLPExtractor", return_value=mock_extractor):
        entities = await parse_query_to_entities("Какие методы обессоливания воды подходят для обогатительной фабрики?")

    assert len(entities) == 2
    assert entities[0].type == "Process"
    assert entities[1].type == "Facility"


@pytest.mark.asyncio
async def test_parse_query_llm_invalid_json_falls_back_to_local():
    mock_extractor = MagicMock()
    mock_extractor.model_id = "gpt://folder/yandexgpt-5.1/latest"
    mock_extractor._use_gemini = False
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content="not json at all", reasoning_content=None))
    ]
    mock_extractor.client.chat.completions.create = AsyncMock(return_value=mock_response)

    with patch("backend.services.query_parse.NLPExtractor", return_value=mock_extractor):
        entities = await parse_query_to_entities("электроэкстракция никеля")

    assert len(entities) > 0


@pytest.mark.asyncio
async def test_bilingual_ontology_aware_local_parse(isolated_db):
    await import_ontology(source="static", database=isolated_db, write_neo4j=False)

    with patch("backend.services.query_parse.db", isolated_db):
        entities = parse_query_local_sync(
            "What electrowinning experiments for Nickel were run at Long Harbour Plant?"
        )

    keys = {e.to_key() for e in entities}
    assert "Process:electrowinning" in keys
    assert "Material:nickel" in keys
    assert "Facility:long harbour plant" in keys


def test_case_spacing_variants_share_canonical_codebook_key(isolated_db):
    isolated_db.get_or_create_vector("Material:Никель")
    isolated_db.get_or_create_vector("Material: никель ")
    isolated_db.get_or_create_vector("Material:НИКЕЛЬ")

    assert "Material:никель" in isolated_db.codebook
    assert "Material:Никель" not in isolated_db.codebook
    assert normalize_entity_key("Material:Никель") == "Material:никель"

    with patch("backend.services.query_parse.db", isolated_db):
        entities = parse_query_local_sync("опыты по Никелю")

    assert any(e.to_key() == "Material:никель" for e in entities)


def test_sparse_codebook_uses_legacy_fallback(tmp_path):
    sparse_db = db.__class__(
        dim=10000,
        embedding_service=EmbeddingService(cache_file=str(tmp_path / "embeddings.pkl")),
    )
    for role in sparse_db.roles:
        sparse_db.codebook[f"Role:{role}"] = sparse_db.vsa.generate_vector()

    with patch("backend.services.query_parse.db", sparse_db):
        entities = parse_query_local_sync("электроэкстракция никеля")

    assert any(e.type == "Process" for e in entities)
    assert any(e.type == "Material" and e.value == "никель" for e in entities)


def test_unknown_coverage_gap_term_does_not_false_positive():
    entities = parse_query_local_sync("Какие способы закачки шахтных вод применялись?")
    assert all("шахтн" not in e.value for e in entities)


@pytest.mark.asyncio
async def test_search_router_uses_shared_parser_fallback():
    """POST /api/search NL path uses the same fallback module as eval."""
    from fastapi.testclient import TestClient
    from backend.app import app

    query = "извлечение меди при pH 2.0"
    expected = parse_query_local_sync(query)

    mock_extractor = MagicMock()
    mock_extractor.client.chat.completions.create = AsyncMock(side_effect=RuntimeError("llm down"))
    mock_extractor.model_id = "gpt://folder/yandexgpt-5.1/latest"
    mock_extractor._use_gemini = False

    with patch("backend.services.query_parse.NLPExtractor", return_value=mock_extractor):
        client = TestClient(app)
        response = client.post(
            "/api/search",
            json={"query": query, "paged": True, "limit": 3},
            headers={"X-User-Name": "test", "X-User-Role": "Administrator"},
        )

    assert response.status_code == 200
    data = response.json()
    if isinstance(data, dict) and data.get("total", 0) > 0:
        assert len(expected) > 0


@pytest.fixture
def isolated_db(tmp_path):
    cache_file = str(tmp_path / "embeddings_cache.pkl")
    db_file = str(tmp_path / "db_state.pkl")
    isolated = db.__class__(
        dim=10000,
        embedding_service=EmbeddingService(cache_file=cache_file),
    )
    isolated.db_filepath = db_file
    return isolated
