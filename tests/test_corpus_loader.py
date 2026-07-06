import os
import tempfile
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from backend.repository.database import HSMEVectorDatabase
from backend.repository.corpus_loader import run_corpus_loader, resolve_data_dir, resolve_target_categories
import argparse

@pytest.fixture
def isolated_db():
    fd, path = tempfile.mkstemp(suffix=".pkl")
    os.close(fd)
    db = HSMEVectorDatabase(dim=1000)
    db.db_filepath = path
    yield db
    if os.path.exists(path):
        os.remove(path)

@pytest.fixture
def mock_args(isolated_db):
    return argparse.Namespace(
        archive_url=None,
        data_dir="data/",
        mode="test",
        max_files=1,
        dry_run=False,
        db_file=isolated_db.db_filepath,
        llm_base_url=None,
        llm_api_key=None,
        llm_folder_id=None,
        llm_model_id=None,
        llm_env_file=".env",
        use_neo4j=False,
        concurrency=1,
    )

@pytest.mark.asyncio
async def test_corpus_loader_test_mode_defaults(isolated_db):
    args = argparse.Namespace(
        archive_url=None,
        data_dir=None,
        mode="test",
        max_files=None,
        dry_run=True,
        db_file=isolated_db.db_filepath,
        llm_base_url=None,
        llm_api_key=None,
        llm_folder_id=None,
        llm_model_id=None,
        llm_env_file=".env",
        use_neo4j=False,
        concurrency=1,
    )
    assert resolve_data_dir(args) == "test_data"
    assert resolve_target_categories("test") == ["Обзоры", "Статьи", "Доклады"]

    with patch("backend.repository.corpus_loader.DocumentParser") as MockParser:
        mock_parser = MockParser.return_value
        mock_parser.scan_directory.return_value = []
        result = await run_corpus_loader(args)
        assert result == 0
        MockParser.assert_called_once_with(target_categories=["Обзоры", "Статьи", "Доклады"])


@pytest.mark.asyncio
async def test_corpus_loader_dry_run(mock_args):
    mock_args.dry_run = True
    
    with patch("backend.repository.corpus_loader.DocumentParser") as MockParser:
        mock_parser = MockParser.return_value
        mock_parser.scan_directory.return_value = ["test.docx"]
        mock_parser.parse_file.return_value = {
            "title": "Test",
            "code": "TEST",
            "chunks": [{"index": 1, "text": "foo", "section": "intro"}]
        }
        
        result = await run_corpus_loader(mock_args)
        assert result == 0

@pytest.mark.asyncio
async def test_corpus_loader_missing_data_dir(mock_args):
    mock_args.data_dir = "nonexistent_dir/"
    result = await run_corpus_loader(mock_args)
    assert result == 1  # Should fail and return 1

@pytest.mark.asyncio
async def test_corpus_loader_downloads_archive(mock_args):
    mock_args.archive_url = "https://disk.yandex.ru/d/test"
    
    with patch("backend.repository.corpus_loader.httpx.AsyncClient") as MockClient, \
         patch("backend.repository.corpus_loader.zipfile.ZipFile") as MockZip, \
         patch("backend.repository.corpus_loader.os.remove"):
        
        # Setup mock client
        mock_client = MockClient.return_value.__aenter__.return_value
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"href": "https://direct.link"}
        mock_client.get = AsyncMock(return_value=mock_response)

        mock_stream_resp = MagicMock()
        mock_stream_resp.raise_for_status = MagicMock()

        async def _aiter_bytes():
            yield b"data"

        mock_stream_resp.aiter_bytes = _aiter_bytes
        mock_stream_cm = MagicMock()
        mock_stream_cm.__aenter__ = AsyncMock(return_value=mock_stream_resp)
        mock_stream_cm.__aexit__ = AsyncMock(return_value=None)
        mock_client.stream = MagicMock(return_value=mock_stream_cm)

        # Bypass actual parsing
        with patch("backend.repository.corpus_loader.IngestionPipeline.ingest_directory", new_callable=AsyncMock) as mock_ingest:
            mock_ingest.return_value = {"files_indexed_count": 1, "total_chunks_indexed": 1, "total_experiments_in_db": 1}
            result = await run_corpus_loader(mock_args)
            assert result == 0
            mock_client.get.assert_awaited_once()
            client_kwargs = MockClient.call_args.kwargs
            assert client_kwargs["verify"] is False
            assert client_kwargs["follow_redirects"] is True
            assert client_kwargs["timeout"].read == 3600.0
            mock_client.stream.assert_called_once()
            assert mock_client.stream.call_args.kwargs.get("follow_redirects") is True

@pytest.mark.asyncio
async def test_corpus_loader_custom_llm(mock_args):
    mock_args.llm_api_key = "test_key"
    mock_args.llm_base_url = "https://custom.url"
    mock_args.dry_run = True
    
    with patch("backend.repository.corpus_loader.NLPExtractor") as MockExtractor, \
         patch("backend.repository.corpus_loader.DocumentParser"):
        
        await run_corpus_loader(mock_args)
        MockExtractor.assert_called_once()
        args, kwargs = MockExtractor.call_args
        assert kwargs.get("api_key") == "test_key"
        assert kwargs.get("base_url") == "https://custom.url"
