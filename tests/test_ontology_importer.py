from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.core.models import Entity
from backend.repository.database import HSMEVectorDatabase
from backend.repository.ontology_importer import (
    STATIC_METALLURGY_ONTOLOGY,
    build_entities_from_ontology,
    classify_wikidata_label,
    fetch_wikidata_ontology,
    import_ontology,
)
from backend.services.embedding import EmbeddingService


@pytest.fixture
def isolated_db(tmp_path):
    cache_file = str(tmp_path / "embeddings_cache.pkl")
    db_file = str(tmp_path / "db_state.pkl")
    db = HSMEVectorDatabase(
        dim=10000,
        embedding_service=EmbeddingService(cache_file=cache_file),
    )
    db.db_filepath = db_file
    return db


def test_classify_wikidata_label():
    assert classify_wikidata_label("Heap leaching process") == "Process"
    assert classify_wikidata_label("Ball mill equipment") == "Equipment"
    assert classify_wikidata_label("Kola MMC plant") == "Facility"
    assert classify_wikidata_label("Pentlandite mineral") == "Material"


def test_build_entities_from_static_ontology():
    entities = build_entities_from_ontology(STATIC_METALLURGY_ONTOLOGY)
    assert len(entities) > 20
    assert any(entity.value == "Никель" and entity.type == "Material" for entity in entities)
    assert any(entity.value == "Electrowinning" and entity.type == "Process" for entity in entities)


@pytest.mark.asyncio
async def test_import_ontology_static_happy_path(isolated_db):
    result = await import_ontology(source="static", database=isolated_db, write_neo4j=False)

    assert result["entity_count"] > 0
    assert result["codebook_size"] >= result["entity_count"]
    assert "Material:Никель" in isolated_db.codebook
    assert "Process:Electrowinning" in isolated_db.codebook


@pytest.mark.asyncio
async def test_import_ontology_wikidata_failure_falls_back_to_static(isolated_db):
    with patch(
        "backend.repository.ontology_importer.fetch_wikidata_ontology",
        new=AsyncMock(side_effect=httpx.RequestError("timeout", request=httpx.Request("GET", "http://test"))),
    ):
        result = await import_ontology(source="wikidata", database=isolated_db, write_neo4j=False)

    assert result["source"] == "wikidata"
    assert result["entity_count"] == len(build_entities_from_ontology(STATIC_METALLURGY_ONTOLOGY))
    assert "Material:Nickel" in isolated_db.codebook


@pytest.mark.asyncio
async def test_import_ontology_skips_neo4j_when_disabled(isolated_db):
    with patch(
        "backend.repository.ontology_importer.neo4j_graph.insert_ontology_entities_async",
        new=AsyncMock(),
    ) as mock_insert:
        result = await import_ontology(source="static", database=isolated_db, write_neo4j=False)

    mock_insert.assert_not_awaited()
    assert result["neo4j_nodes_written"] == 0
    assert result["entity_count"] > 0


@pytest.mark.asyncio
async def test_fetch_wikidata_ontology_parses_bindings():
    payload = {
        "results": {
            "bindings": [
                {"itemLabel": {"value": "Heap leaching"}},
                {"itemLabel": {"value": "Ball mill"}},
                {"itemLabel": {"value": "Nickel"}},
            ]
        }
    }

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = payload

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("backend.repository.ontology_importer.httpx.AsyncClient", return_value=mock_client):
        data = await fetch_wikidata_ontology(limit=10)

    assert "Heap leaching" in data["Process"]
    assert "Ball mill" in data["Equipment"]
    assert "Nickel" in data["Material"]


@pytest.mark.asyncio
async def test_neo4j_insert_ontology_entities_async_dry_run():
    from backend.repository.neo4j_graph import Neo4jGraphRepository

    repo = Neo4jGraphRepository(enabled=True, dry_run=True)
    entities = [Entity(type="Material", value="Никель")]
    written = await repo.insert_ontology_entities_async(entities)
    assert written == 1
