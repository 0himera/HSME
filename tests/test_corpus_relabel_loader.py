import argparse
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.models import Entity, Experiment
from backend.repository.corpus_relabel_loader import (
    RelabelIngestionPipeline,
    build_llm_extractor,
    build_yandex_extractor,
    resolve_yandex_concurrency,
    run_corpus_relabel_loader,
    write_ingestion_report,
)
from backend.services.ingestion import make_experiment_id
from backend.repository.database import HSMEVectorDatabase
from backend.repository.neo4j_graph import Neo4jGraphRepository


@pytest.fixture
def isolated_db():
    fd, path = tempfile.mkstemp(suffix=".pkl")
    os.close(fd)
    db = HSMEVectorDatabase(dim=1000)
    db.db_filepath = path
    db.experiments["EXP-OLD-01"] = Experiment(
        id="EXP-OLD-01",
        name="Old experiment",
        input_entities=[Entity(type="Material", value="Nickel")],
        process_entities=[],
        output_entities=[],
    )
    db.vector_store["EXP-OLD-01"] = db.encode_experiment(db.experiments["EXP-OLD-01"])
    yield db
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def relabel_args(isolated_db):
    return argparse.Namespace(
        archive_url=None,
        data_dir="test_data",
        mode="test",
        max_files=1,
        dry_run=False,
        db_file=isolated_db.db_filepath,
        llm_env_file="/nonexistent/.env",
        use_llm=False,
        llm_api_key=None,
        llm_base_url=None,
        llm_folder_id=None,
        llm_model_id=None,
        yandex_api_key="AQVNtest",
        yandex_folder_id="b1gtest",
        yandex_base_url="https://ai.api.cloud.yandex.net/v1",
        yandex_model="yandexgpt-5.1/latest",
        clear_neo4j=False,
        use_neo4j=False,
        concurrency=3,
        skip_files=0,
    )


def test_resolve_yandex_concurrency_caps_at_safe_max():
    assert resolve_yandex_concurrency(3) == 3
    assert resolve_yandex_concurrency(20) == 8
    assert resolve_yandex_concurrency(0) == 3


def test_build_llm_extractor_uses_llm_settings():
    args = argparse.Namespace(
        llm_api_key="sk-test",
        llm_base_url="https://api.proxyapi.ru/openai/v1",
        llm_folder_id=None,
        llm_model_id="gpt-4o-mini",
        llm_env_file="/nonexistent/.env",
    )
    with patch("backend.repository.corpus_relabel_loader.NLPExtractor") as mock_extractor:
        build_llm_extractor(args)
        kwargs = mock_extractor.call_args.kwargs
        assert kwargs["api_key"] == "sk-test"
        assert kwargs["base_url"] == "https://api.proxyapi.ru/openai/v1"
        assert kwargs["model_id"] == "gpt-4o-mini"


def test_build_yandex_extractor_uses_yandexgpt_51():
    args = argparse.Namespace(
        yandex_api_key="AQVNtest",
        yandex_folder_id="b1gfolder",
        yandex_base_url="https://ai.api.cloud.yandex.net/v1",
        yandex_model="yandexgpt-5.1/latest",
        llm_env_file="/nonexistent/.env",
    )
    with patch("backend.repository.corpus_relabel_loader.NLPExtractor") as mock_extractor:
        build_yandex_extractor(args)
        kwargs = mock_extractor.call_args.kwargs
        assert kwargs["api_key"] == "AQVNtest"
        assert kwargs["folder_id"] == "b1gfolder"
        assert kwargs["base_url"] == "https://ai.api.cloud.yandex.net/v1"
        assert kwargs["model_id"] == "gpt://b1gfolder/yandexgpt-5.1/latest"


@pytest.mark.asyncio
async def test_relabel_pipeline_overwrites_existing_experiment(isolated_db):
    pipeline = RelabelIngestionPipeline(isolated_db, concurrency_limit=1, extractor=MagicMock())
    pipeline.extractor.extract_entities_and_relations = AsyncMock(
        return_value={
            "entities": [{"type": "Material", "value": "Updated nickel"}],
            "relations": [],
        }
    )

    chunk = {"index": 1, "text": "Updated chunk", "section": "Intro"}
    doc_meta = {
        "code": "OLD",
        "title": "Updated title",
        "authors": ["Не указан"],
        "filename": "doc.pdf",
        "year": 2024,
        "source_type": "Статья",
    }

    with patch("backend.services.ingestion.neo4j_graph") as mock_graph:
        mock_graph.is_configured = False
        await pipeline.process_chunk(chunk, doc_meta)

    assert "EXP-OLD-01" in isolated_db.experiments
    assert isolated_db.experiments["EXP-OLD-01"].input_entities[0].value == "Updated nickel"
    pipeline.extractor.extract_entities_and_relations.assert_awaited_once()


@pytest.mark.asyncio
async def test_relabel_pipeline_restores_previous_on_failed_extraction(isolated_db):
    pipeline = RelabelIngestionPipeline(isolated_db, concurrency_limit=1, extractor=MagicMock())
    pipeline.extractor.extract_entities_and_relations = AsyncMock(
        return_value={"entities": [], "relations": []}
    )

    chunk = {"index": 1, "text": "empty", "section": "Intro"}
    doc_meta = {
        "code": "OLD",
        "title": "Old title",
        "authors": ["Не указан"],
        "filename": "doc.pdf",
        "year": 2024,
        "source_type": "Статья",
    }

    with patch("backend.services.ingestion.neo4j_graph") as mock_graph:
        mock_graph.is_configured = False
        await pipeline.process_chunk(chunk, doc_meta)

    assert isolated_db.experiments["EXP-OLD-01"].input_entities[0].value == "Nickel"


@pytest.mark.asyncio
async def test_run_relabel_loader_missing_yandex_creds(relabel_args, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("# no yandex creds\n", encoding="utf-8")
    relabel_args.llm_env_file = str(env_file)
    relabel_args.yandex_api_key = ""
    relabel_args.yandex_folder_id = ""
    for name in ("YANDEX_API_KEY", "YANDEX_FOLDER_ID", "LLM_API_KEY", "LLM_FOLDER_ID"):
        monkeypatch.delenv(name, raising=False)

    def exists(path: str) -> bool:
        return path in ("test_data", str(env_file))

    with patch("backend.repository.corpus_relabel_loader.os.path.exists", side_effect=exists):
        result = await run_corpus_relabel_loader(relabel_args)
    assert result == 2


@pytest.mark.asyncio
async def test_run_relabel_loader_clear_neo4j(relabel_args):
    relabel_args.clear_neo4j = True
    relabel_args.use_neo4j = True
    relabel_args.dry_run = False

    with patch("backend.repository.corpus_relabel_loader.os.path.exists", return_value=True), \
         patch("backend.repository.corpus_relabel_loader.build_extractor") as mock_build, \
         patch("backend.repository.corpus_relabel_loader.HSMEVectorDatabase") as mock_db_cls, \
         patch("backend.repository.neo4j_graph.neo4j_graph") as mock_graph, \
         patch("backend.repository.corpus_relabel_loader.RelabelIngestionPipeline") as mock_pipeline_cls:

        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        mock_build.return_value = MagicMock(model_id="gpt://b1g/yandexgpt-5.1/latest")
        mock_graph.is_configured = True
        mock_graph.clear_all_async = AsyncMock(
            return_value={"nodes_deleted": 10, "relationships_deleted": 25}
        )
        mock_graph.insert_experiment_async = AsyncMock(return_value=True)
        mock_graph.ensure_indexes = AsyncMock(return_value=True)
        mock_graph.close = AsyncMock()
        mock_pipeline_cls.return_value.ingest_directory = AsyncMock(
            return_value={
                "files_indexed_count": 1,
                "total_chunks_indexed": 2,
                "total_experiments_in_db": 3,
            }
        )

        result = await run_corpus_relabel_loader(relabel_args)

    assert result == 0
    mock_graph.clear_all_async.assert_awaited_once()
    assert mock_graph.ensure_indexes.await_count >= 1


@pytest.mark.asyncio
async def test_run_relabel_loader_dry_run_reports_clear_neo4j(relabel_args, caplog):
    relabel_args.dry_run = True
    relabel_args.clear_neo4j = True

    with patch("backend.repository.corpus_relabel_loader.os.path.exists", return_value=True), \
         patch("backend.repository.corpus_relabel_loader.build_extractor") as mock_build, \
         patch("backend.repository.corpus_relabel_loader.HSMEVectorDatabase") as mock_db_cls, \
         patch("backend.repository.corpus_relabel_loader.DocumentParser") as mock_parser_cls:

        mock_build.return_value = MagicMock(model_id="gpt://b1g/yandexgpt-5.1/latest")
        mock_db_cls.return_value = MagicMock()
        mock_parser = mock_parser_cls.return_value
        mock_parser.scan_directory.return_value = ["file.docx"]
        mock_parser.parse_file.return_value = {
            "code": "DOC",
            "chunks": [{"index": 1, "text": "x", "section": "s"}],
        }

        with caplog.at_level("INFO"):
            result = await run_corpus_relabel_loader(relabel_args)

    assert result == 0
    assert "would clear Neo4j graph" in caplog.text


@pytest.mark.asyncio
async def test_neo4j_clear_all_dry_run():
    repo = Neo4jGraphRepository(enabled=True, dry_run=True)
    stats = await repo.clear_all_async()
    assert stats["dry_run"] is True
    assert stats["nodes_deleted"] == 0


@pytest.mark.asyncio
async def test_neo4j_clear_all_executes_delete():
    repo = Neo4jGraphRepository(enabled=True, dry_run=False)
    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None

    count_result = MagicMock()
    count_result.single = AsyncMock(return_value={"nodes": 5, "rels": 12})
    mock_session.run = AsyncMock(side_effect=[count_result, None])

    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session

    with patch.object(repo, "_get_driver", return_value=mock_driver):
        stats = await repo.clear_all_async()

    assert stats["nodes_deleted"] == 5
    assert stats["relationships_deleted"] == 12
    assert mock_session.run.await_count == 2
    assert "DETACH DELETE" in mock_session.run.await_args_list[1].args[0]


@pytest.mark.asyncio
async def test_ingest_directory_skip_files(isolated_db):
    pipeline = RelabelIngestionPipeline(isolated_db, concurrency_limit=1, extractor=MagicMock())
    pipeline.extractor.extract_entities_and_relations = AsyncMock(
        return_value={"entities": [], "relations": []}
    )
    mock_parser = MagicMock()
    mock_parser.scan_directory.return_value = ["a.docx", "b.docx", "c.docx"]
    mock_parser.parse_file.return_value = {
        "code": "DOC",
        "title": "Doc",
        "authors": ["Не указан"],
        "filename": "b.docx",
        "year": 2024,
        "chunks": [{"index": 0, "text": "x", "section": "s"}],
    }
    pipeline.parser = mock_parser

    with patch("backend.services.ingestion.neo4j_graph") as mock_graph:
        mock_graph.is_configured = False
        stats = await pipeline.ingest_directory(
            "test_data",
            max_files=10,
            skip_files=1,
        )

    assert stats["files_skipped_count"] == 1
    assert stats["files_indexed_count"] == 2
    assert mock_parser.parse_file.call_count == 4


@pytest.mark.asyncio
async def test_run_relabel_loader_passes_skip_files(relabel_args):
    relabel_args.skip_files = 2

    with patch("backend.repository.corpus_relabel_loader.os.path.exists", return_value=True), \
         patch("backend.repository.corpus_relabel_loader.build_extractor") as mock_build, \
         patch("backend.repository.corpus_relabel_loader.HSMEVectorDatabase") as mock_db_cls, \
         patch("backend.repository.corpus_relabel_loader.RelabelIngestionPipeline") as mock_pipeline_cls:

        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        mock_build.return_value = MagicMock(model_id="gpt://b1g/yandexgpt-5.1/latest")
        ingest = AsyncMock(
            return_value={
                "files_indexed_count": 1,
                "total_chunks_indexed": 5,
                "files_skipped_count": 2,
                "total_experiments_in_db": 4,
            }
        )
        mock_pipeline_cls.return_value.ingest_directory = ingest

        result = await run_corpus_relabel_loader(relabel_args)

    assert result == 0
    assert ingest.await_args.kwargs["skip_files"] == 2


@pytest.mark.asyncio
async def test_relabel_no_cross_file_restore(isolated_db):
    pipeline = RelabelIngestionPipeline(isolated_db, concurrency_limit=1, extractor=MagicMock())
    pipeline.extractor.extract_entities_and_relations = AsyncMock(
        return_value={"entities": [], "relations": [], "_skip_reason": "validation_failed"}
    )

    doc_a = {
        "code": "N/A",
        "title": "Journal A",
        "authors": ["Не указан"],
        "filename": "journal_a.pdf",
        "file_slug": "JOURNAL-A",
        "year": 2024,
        "source_type": "Журнал",
    }
    doc_b = {
        "code": "N/A",
        "title": "Journal B",
        "authors": ["Не указан"],
        "filename": "journal_b.pdf",
        "file_slug": "JOURNAL-B",
        "year": 2024,
        "source_type": "Журнал",
    }
    chunk = {"index": 0, "text": "empty", "section": "Intro"}
    id_a = make_experiment_id(doc_a, 0)
    id_b = make_experiment_id(doc_b, 0)

    isolated_db.experiments[id_a] = Experiment(
        id=id_a,
        name="A",
        input_entities=[Entity(type="Material", value="Alpha")],
        process_entities=[],
        output_entities=[],
    )
    isolated_db.vector_store[id_a] = isolated_db.encode_experiment(isolated_db.experiments[id_a])
    isolated_db.experiments[id_b] = Experiment(
        id=id_b,
        name="B",
        input_entities=[Entity(type="Material", value="Beta")],
        process_entities=[],
        output_entities=[],
    )
    isolated_db.vector_store[id_b] = isolated_db.encode_experiment(isolated_db.experiments[id_b])

    with patch("backend.services.ingestion.neo4j_graph") as mock_graph:
        mock_graph.is_configured = False
        await pipeline.process_chunk(chunk, doc_a)
        await pipeline.process_chunk(chunk, doc_b)

    assert isolated_db.experiments[id_a].input_entities[0].value == "Alpha"
    assert isolated_db.experiments[id_b].input_entities[0].value == "Beta"


def test_write_ingestion_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stats = {
        "counts": {"ok": 2, "restored": 1, "skipped": 0, "validation_failed": 0, "moderation": 0, "empty": 0},
        "files_indexed_count": 1,
        "total_chunks_indexed": 3,
        "files_skipped_count": 0,
        "total_experiments_in_db": 5,
        "chunk_outcomes": [{"experiment_id": "EXP-X-00", "status": "ok"}],
    }
    path = write_ingestion_report(stats, run_id="20260705T000000Z")
    assert path.exists()
    assert path.name == "summary.json"
    assert "20260705T000000Z" in str(path)


@pytest.mark.asyncio
async def test_run_relabel_loader_writes_summary_json(relabel_args, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    relabel_args.use_neo4j = False

    with patch("backend.repository.corpus_relabel_loader.os.path.exists", return_value=True), \
         patch("backend.repository.corpus_relabel_loader.build_extractor") as mock_build, \
         patch("backend.repository.corpus_relabel_loader.HSMEVectorDatabase") as mock_db_cls, \
         patch("backend.repository.corpus_relabel_loader.RelabelIngestionPipeline") as mock_pipeline_cls:

        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        mock_build.return_value = MagicMock(model_id="gpt://b1g/yandexgpt-5.1/latest")
        mock_pipeline_cls.return_value.ingest_directory = AsyncMock(
            return_value={
                "files_indexed_count": 1,
                "total_chunks_indexed": 2,
                "files_skipped_count": 0,
                "total_experiments_in_db": 3,
                "counts": {"ok": 2, "restored": 0, "skipped": 0, "validation_failed": 0, "moderation": 0, "empty": 0},
                "chunk_outcomes": [],
            }
        )

        result = await run_corpus_relabel_loader(relabel_args)

    assert result == 0
    reports = list(tmp_path.glob("ingestion_reports/*/summary.json"))
    assert len(reports) == 1
