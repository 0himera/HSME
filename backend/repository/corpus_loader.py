"""Standalone entrypoint for downloading and ingesting the HSME corpus."""

import argparse
import asyncio
import logging
import sys
import os
import zipfile
import shutil
from pathlib import Path
from typing import Optional

import httpx

from backend.core.config import resolve_llm_settings

# Pre-set config environment before importing backend modules
os.environ["HSME_DATABASE_FILE"] = os.environ.get("HSME_DATABASE_FILE", "db_state.pkl")

from backend.repository.database import HSMEVectorDatabase
from backend.services.document_parser import DocumentParser
from backend.services.nlp_extractor import NLPExtractor
from backend.services.ingestion import IngestionPipeline, make_experiment_id

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_ARCHIVE_URL = "https://disk.yandex.ru/d/npigiuw4Rbe9Pg"
TEST_DATA_DIR = "test_data"
PROD_DATA_DIR = "data"
TEST_TARGET_CATEGORIES = ["Обзоры", "Статьи", "Доклады"]


def resolve_data_dir(args: argparse.Namespace) -> str | None:
    """Pick corpus root: explicit flag > test default > prod default."""
    if args.data_dir:
        return args.data_dir
    if args.mode == "test":
        return TEST_DATA_DIR
    return PROD_DATA_DIR


def resolve_target_categories(mode: str) -> list[str] | None:
    """In test mode ingest only research folders Обзоры/Статьи/Доклады."""
    if mode == "test":
        return TEST_TARGET_CATEGORIES
    return None

async def download_and_extract_yandex_archive(public_url: str, extract_dir: str) -> str:
    """Downloads a public archive from Yandex Disk and extracts it."""
    logger.info("Resolving Yandex Disk public URL: %s", public_url)
    api_url = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
    params = {"public_key": public_url}
    # Yandex zip links redirect (302) and the archive can be multi-GB.
    timeout = httpx.Timeout(60.0, connect=60.0, read=3600.0, write=60.0, pool=60.0)

    async with httpx.AsyncClient(verify=False, follow_redirects=True, timeout=timeout) as client:
        resp = await client.get(api_url, params=params)
        if resp.status_code != 200:
            logger.error("Failed to resolve URL: %s", resp.text)
            resp.raise_for_status()

        download_url = resp.json().get("href")
        if not download_url:
            raise ValueError("Could not resolve download URL from Yandex Disk.")

        logger.info("Downloading archive...")
        archive_path = os.path.join(extract_dir, "corpus.zip")
        os.makedirs(extract_dir, exist_ok=True)

        async with client.stream("GET", download_url, follow_redirects=True) as stream_resp:
            stream_resp.raise_for_status()
            downloaded = 0
            with open(archive_path, "wb") as f:
                async for chunk in stream_resp.aiter_bytes():
                    f.write(chunk)
                    downloaded += len(chunk)
                    if downloaded and downloaded % (100 * 1024 * 1024) < len(chunk):
                        logger.info("Downloaded %.1f MB...", downloaded / (1024 * 1024))

        logger.info("Extracting archive to %s", extract_dir)
        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
            
        os.remove(archive_path)
        return extract_dir

async def run_corpus_loader(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    cache_dir = None
    target_categories = resolve_target_categories(args.mode)
    
    if args.archive_url:
        cache_dir = ".cache/hsme_corpus_loader"
        os.makedirs(cache_dir, exist_ok=True)
        try:
            data_dir = await download_and_extract_yandex_archive(args.archive_url, cache_dir)
        except Exception as e:
            logger.error("Failed to fetch Yandex Disk archive: %s: %s", type(e).__name__, e)
            return 1
        
    if not os.path.exists(data_dir):
        logger.error("Data directory '%s' not found.", data_dir)
        return 1
        
    logger.info("Using data directory: %s", data_dir)
    if target_categories:
        logger.info("Target folders: %s", ", ".join(target_categories))
    
    # Determine the database file
    db_file = args.db_file or os.environ.get("HSME_DATABASE_FILE", "db_state.pkl")
    os.environ["HSME_DATABASE_FILE"] = db_file
    
    if not args.use_neo4j:
        os.environ["USE_NEO4J"] = "false"
        
    # Re-import neo4j_graph after setting env vars just in case (though it might already be loaded)
    from backend.repository.neo4j_graph import neo4j_graph
    
    # Ensure Neo4j configuration matches args
    neo4j_graph.enabled = args.use_neo4j
        
    logger.info("Loading vector database from %s...", db_file)
    db = HSMEVectorDatabase(dim=10000)
    db.db_filepath = db_file
    db.load_from_disk(db_file)
    
    llm_settings = resolve_llm_settings(
        api_key=args.llm_api_key,
        base_url=args.llm_base_url,
        folder_id=args.llm_folder_id,
        model_id=args.llm_model_id,
        env_file=args.llm_env_file,
    )
    if llm_settings:
        logger.info("LLM config loaded (env file: %s)", args.llm_env_file)

    extractor_args = {}
    if llm_settings.get("LLM_API_KEY"):
        extractor_args["api_key"] = llm_settings["LLM_API_KEY"]
    if llm_settings.get("LLM_FOLDER_ID"):
        extractor_args["folder_id"] = llm_settings["LLM_FOLDER_ID"]
    if llm_settings.get("LLM_BASE_URL"):
        extractor_args["base_url"] = llm_settings["LLM_BASE_URL"]
    if llm_settings.get("LLM_MODEL_ID"):
        extractor_args["model_id"] = llm_settings["LLM_MODEL_ID"]
    
    extractor = NLPExtractor(**extractor_args) if extractor_args else None
    
    # Determine file limit
    limit = args.max_files if args.max_files is not None else (15 if args.mode == "test" else 999999)
    skip_files = max(0, getattr(args, "skip_files", 0) or 0)
    if args.max_files is None and args.mode == "test" and skip_files > 0:
        limit = max(0, limit - skip_files)
    
    # Adjust concurrency if we are using an external service like OpenRouter which may rate limit more aggressively
    concurrency_limit = args.concurrency
    if args.llm_base_url and "openrouter.ai" in args.llm_base_url and args.concurrency == 6:
        # Default concurrency is 6, which might be too high for free OpenRouter accounts
        concurrency_limit = 2
        logger.info("Automatically reduced concurrency to %d for OpenRouter to avoid rate limits.", concurrency_limit)

    pipeline = IngestionPipeline(db, concurrency_limit=concurrency_limit, extractor=extractor)
    
    if args.dry_run:
        logger.info("DRY RUN: Scanning up to %d files in %s...", limit, data_dir)
        parser = DocumentParser(target_categories=target_categories) if target_categories else DocumentParser()
        files = parser.scan_directory(data_dir)
        files.sort(key=lambda x: 0 if "Обзоры" in x else (1 if "Статьи" in x else 2))
        if skip_files:
            files = files[skip_files:]
        files = files[:limit]
        
        total_chunks = 0
        new_chunks = 0
        for f in files:
            doc = parser.parse_file(f)
            if doc and doc["chunks"]:
                total_chunks += len(doc["chunks"])
                for chunk in doc["chunks"]:
                    exp_id = make_experiment_id(doc, chunk["index"])
                    if exp_id not in db.experiments:
                        new_chunks += 1
                        
        logger.info(
            "Dry run complete. Skipped %d file(s). Files scanned: %d. Total chunks: %d. New chunks to process: %d.",
            skip_files,
            len(files),
            total_chunks,
            new_chunks,
        )
    else:
        logger.info(
            "Running ingestion (mode=%s, max_files=%d, skip_files=%d)...",
            args.mode,
            limit,
            skip_files,
        )
        
        # Override neo4j behavior if necessary
        if args.use_neo4j and neo4j_graph.is_configured:
            await neo4j_graph.ensure_indexes()
            
        stats = await pipeline.ingest_directory(
            data_dir,
            max_files=limit,
            target_categories=target_categories,
            skip_files=skip_files,
        )
        
        logger.info(
            "Ingestion complete. Skipped %d file(s). Processed %d files (%d chunks). Total DB size: %d.",
            stats.get("files_skipped_count", 0),
            stats.get("files_indexed_count", 0),
            stats.get("total_chunks_indexed", 0),
            stats.get("total_experiments_in_db", 0),
        )
        
    return 0

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Standalone HSME corpus ingestion loader.")
    parser.add_argument("--archive-url", type=str, help="Public URL of a Yandex Disk folder/archive")
    parser.add_argument("--mode", type=str, choices=["test", "prod"], default="test", help="Run mode: 'test' (limited files) or 'prod' (all files)")
    parser.add_argument("--max-files", type=int, help="Override the maximum number of files to process")
    parser.add_argument(
        "--skip-files",
        type=int,
        default=0,
        help="Skip the first N files in the sorted corpus list (resume after interrupt)",
    )
    parser.add_argument("--data-dir", type=str, help="Local corpus root (test default: test_data/, prod default: data/)")
    parser.add_argument("--db-file", type=str, help="Path to the output pickle file")
    
    # LLM Overrides (optional; fallback to .env / env vars)
    parser.add_argument("--llm-env-file", type=str, default=".env", help="Path to dotenv file with LLM_API_KEY and LLM_BASE_URL")
    parser.add_argument("--llm-base-url", type=str, help="Custom LLM API base URL")
    parser.add_argument("--llm-api-key", type=str, help="Custom LLM API key")
    parser.add_argument("--llm-folder-id", type=str, dest="llm_folder_id", help="Yandex Cloud catalog ID for LLM (optional; defaults from nlp_extractor.py)")
    parser.add_argument("--llm-model-id", type=str, help="Custom LLM Model ID")
    
    # Options
    parser.add_argument("--no-neo4j", action="store_false", dest="use_neo4j", help="Disable dual-write to Neo4j")
    parser.add_argument("--dry-run", action="store_true", help="Parse files and count chunks, but do not call LLM or write to DB")
    parser.add_argument("--concurrency", type=int, default=6, help="Concurrent chunks to process (default: 6)")
    
    args = parser.parse_args(argv)
    return asyncio.run(run_corpus_loader(args))

if __name__ == "__main__":
    sys.exit(main())
