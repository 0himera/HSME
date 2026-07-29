import pytest
from unittest.mock import AsyncMock, patch

from backend.repository.database import HSMEVectorDatabase
from backend.services.ingestion import (
    IngestionPipeline,
    has_domain_evidence,
    is_low_signal_chunk,
)


def test_is_low_signal_chunk_too_short():
    skip, reason = is_low_signal_chunk("Цель курса")
    assert skip is True
    assert reason in {"too_short", "presentation_boilerplate", "too_few_tokens"}


def test_is_low_signal_chunk_presentation_boilerplate():
    skip, reason = is_low_signal_chunk("Результат обучения.\nЦель курса")
    assert skip is True
    assert reason in {
        "presentation_boilerplate",
        "low_domain_signal",
        "too_few_tokens",
        "too_short",
    }


def test_is_low_signal_chunk_keeps_domain_text():
    text = (
        "Электроэкстракция никеля из сульфатного электролита при pH 2.0 "
        "и плотности тока 300 А/м2 обеспечивает выход по току 95%."
    )
    skip, reason = is_low_signal_chunk(text)
    assert skip is False
    assert reason == ""


def test_has_domain_evidence_requires_core_types():
    assert has_domain_evidence(
        [{"type": "Publication", "value": "Обзор"}, {"type": "Expert", "value": "Иванов"}]
    ) is False
    assert has_domain_evidence([{"type": "Material", "value": "никель"}]) is True


@pytest.mark.asyncio
async def test_process_chunk_skips_llm_for_low_signal(tmp_path):
    db = HSMEVectorDatabase(dim=10000)
    db.db_filepath = str(tmp_path / "db.pkl")
    pipeline = IngestionPipeline(db, concurrency_limit=1)
    pipeline.extractor.extract_entities_and_relations = AsyncMock(
        return_value={"entities": [{"type": "Material", "value": "никель"}], "relations": []}
    )
    chunk = {"index": 1, "text": "12", "section": "Слайд"}
    doc_meta = {
        "title": "Доклад",
        "authors": ["Не указан"],
        "filename": "slide.pdf",
        "code": "SLIDE",
        "year": 2024,
        "source_type": "Доклад",
    }
    with patch("backend.services.ingestion.neo4j_graph") as mock_graph:
        mock_graph.is_configured = False
        status = await pipeline.process_chunk(chunk, doc_meta)

    assert status == "empty"
    pipeline.extractor.extract_entities_and_relations.assert_not_awaited()
    assert pipeline.chunk_outcomes[-1]["skip_reason"] == "low_signal_prefilter"


@pytest.mark.asyncio
async def test_process_chunk_rejects_publication_only_ok(tmp_path):
    db = HSMEVectorDatabase(dim=10000)
    db.db_filepath = str(tmp_path / "db.pkl")
    pipeline = IngestionPipeline(db, concurrency_limit=1)
    pipeline.extractor.extract_entities_and_relations = AsyncMock(
        return_value={
            "entities": [
                {"type": "Publication", "value": "Тематическая информация"},
                {"type": "Expert", "value": "Вострикова Н.М."},
            ],
            "relations": [],
        }
    )
    chunk = {
        "index": 1,
        "text": (
            "Электроэкстракция никеля из сульфатного электролита при pH 2.0 "
            "и плотности тока 300 А/м2 описана в тематической информации."
        ),
        "section": "Введение",
    }
    doc_meta = {
        "title": "Тематическая информация",
        "authors": ["Вострикова Н.М."],
        "filename": "bim.docx",
        "code": "BIM",
        "year": 2024,
        "source_type": "Обзор",
    }
    with patch("backend.services.ingestion.neo4j_graph") as mock_graph:
        mock_graph.is_configured = False
        status = await pipeline.process_chunk(chunk, doc_meta)

    assert status == "empty"
    assert pipeline.chunk_outcomes[-1]["skip_reason"] == "weak_domain_evidence"
    assert len(db.experiments) == 0
