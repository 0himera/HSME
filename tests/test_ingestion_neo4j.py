"""Tests for VSA-first dual-write in ingestion pipeline."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, patch

import pytest

from backend.repository.database import HSMEVectorDatabase
from backend.services.ingestion import IngestionPipeline


@pytest.fixture
def isolated_db():
    fd, path = tempfile.mkstemp(suffix=".pkl")
    os.close(fd)
    db = HSMEVectorDatabase(dim=1000)
    db.db_filepath = path
    yield db
    if os.path.exists(path):
        os.remove(path)


def _doc_meta() -> dict:
    return {
        "title": "Test publication",
        "authors": ["Author One"],
        "filename": "test.docx",
        "code": "TEST",
        "year": 2024,
        "source_type": "Article",
    }


def _chunk() -> dict:
    return {
        "text": "Nickel electrowinning at pH 2.0",
        "index": 1,
        "section": "Methods",
    }


@pytest.mark.asyncio
async def test_process_chunk_dual_write_invokes_neo4j(isolated_db):
    db = isolated_db
    pipeline = IngestionPipeline(db, concurrency_limit=1)

    extractor_result = {
        "entities": [
            {"type": "Material", "value": "Nickel electrolyte"},
            {"type": "Process", "value": "Electrowinning"},
        ],
        "relations": [],
    }

    pipeline.extractor.extract_entities_and_relations = AsyncMock(return_value=extractor_result)

    with patch("backend.services.ingestion.neo4j_graph") as mock_graph:
        mock_graph.is_configured = True
        mock_graph.insert_experiment_async = AsyncMock(return_value=True)

        await pipeline.process_chunk(_chunk(), _doc_meta())

        assert len(db.experiments) == 1
        exp = next(iter(db.experiments.values()))
        mock_graph.insert_experiment_async.assert_awaited_once_with(exp)


@pytest.mark.asyncio
async def test_process_chunk_vsa_first_when_neo4j_fails(isolated_db):
    db = isolated_db
    pipeline = IngestionPipeline(db, concurrency_limit=1)

    extractor_result = {
        "entities": [
            {"type": "Material", "value": "Copper ore"},
            {"type": "Process", "value": "Leaching"},
        ],
        "relations": [],
    }

    pipeline.extractor.extract_entities_and_relations = AsyncMock(return_value=extractor_result)

    with patch("backend.services.ingestion.neo4j_graph") as mock_graph:
        mock_graph.is_configured = True
        mock_graph.insert_experiment_async = AsyncMock(side_effect=ConnectionError("neo4j down"))

        await pipeline.process_chunk(_chunk(), _doc_meta())

        assert len(db.experiments) == 1
        exp = next(iter(db.experiments.values()))
        assert any(e.type == "Material" and e.value == "Copper ore" for e in exp.input_entities)
