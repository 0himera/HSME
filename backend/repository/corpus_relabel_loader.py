"""Re-label corpus with YandexGPT 5.1 and optional Neo4j graph reset.

Based on corpus_loader.py, but always re-processes chunks (overwrites VSA)
and defaults to Yandex AI Studio yandexgpt-5.1/latest.

Yandex AI Studio generation quota (see docs): up to ~500 requests/minute;
default concurrency is capped conservatively at 3.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.core.config import resolve_llm_settings
from backend.repository.corpus_loader import (
    DEFAULT_ARCHIVE_URL,
    PROD_DATA_DIR,
    TEST_DATA_DIR,
    TEST_TARGET_CATEGORIES,
    download_and_extract_yandex_archive,
    resolve_data_dir,
    resolve_target_categories,
)
from backend.services.document_parser import DocumentParser
from backend.services.ingestion import IngestionPipeline, make_experiment_id
from backend.services.nlp_extractor import NLPExtractor
from backend.services.yandex_aistudio_client import (
    DEFAULT_MODEL_SLUG,
    YandexAIStudioConfigError,
    resolve_yandex_config,
)

# Pre-set config environment before importing backend modules
os.environ["HSME_DATABASE_FILE"] = os.environ.get("HSME_DATABASE_FILE", ".local/db_state.pkl")

from backend.repository.database import HSMEVectorDatabase  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

YANDEX_DEFAULT_CONCURRENCY = 3
YANDEX_SAFE_MAX_CONCURRENCY = 8


def resolve_yandex_concurrency(requested: int) -> int:
    """Cap concurrent LLM calls to stay within Yandex AI Studio quotas."""
    if requested <= 0:
        return YANDEX_DEFAULT_CONCURRENCY
    return min(requested, YANDEX_SAFE_MAX_CONCURRENCY)


def build_yandex_extractor(args: argparse.Namespace) -> NLPExtractor:
    config = resolve_yandex_config(
        api_key=args.yandex_api_key,
        folder_id=args.yandex_folder_id,
        base_url=args.yandex_base_url,
        model_slug=args.yandex_model,
        env_file=args.llm_env_file,
    )
    logger.info(
        "Using Yandex model %s via %s",
        config.model_uri,
        config.base_url,
    )
    return NLPExtractor(
        api_key=config.api_key,
        folder_id=config.folder_id,
        base_url=config.base_url,
        model_id=config.model_uri,
    )


def build_llm_extractor(args: argparse.Namespace) -> NLPExtractor:
    llm_settings = resolve_llm_settings(
        api_key=args.llm_api_key,
        base_url=args.llm_base_url,
        folder_id=args.llm_folder_id,
        model_id=args.llm_model_id,
        env_file=args.llm_env_file,
    )
    if not llm_settings.get("LLM_API_KEY"):
        raise YandexAIStudioConfigError(
            "LLM_API_KEY is missing. Set it in the environment, .env file, or pass --llm-api-key."
        )
    model_id = llm_settings.get("LLM_MODEL_ID", "unknown")
    base_url = llm_settings.get("LLM_BASE_URL", "default")
    logger.info("Using LLM model %s via %s", model_id, base_url)

    extractor_args: dict[str, str] = {"api_key": llm_settings["LLM_API_KEY"]}
    if llm_settings.get("LLM_FOLDER_ID"):
        extractor_args["folder_id"] = llm_settings["LLM_FOLDER_ID"]
    if llm_settings.get("LLM_BASE_URL"):
        extractor_args["base_url"] = llm_settings["LLM_BASE_URL"]
    if llm_settings.get("LLM_MODEL_ID"):
        extractor_args["model_id"] = llm_settings["LLM_MODEL_ID"]
    return NLPExtractor(**extractor_args)


def build_extractor(args: argparse.Namespace) -> NLPExtractor:
    if args.use_llm:
        return build_llm_extractor(args)
    return build_yandex_extractor(args)


class RelabelIngestionPipeline(IngestionPipeline):
    """Re-runs NLP extraction even when an experiment id already exists in VSA."""

    async def process_chunk(self, chunk: dict[str, Any], doc_meta: dict[str, Any]) -> str:
        exp_id = make_experiment_id(doc_meta, chunk["index"])
        previous = self.db.experiments.get(exp_id)
        previous_vector = self.db.vector_store.get(exp_id)
        if previous is not None:
            logger.info("Re-labeling existing experiment %s", exp_id)
            self.db.experiments.pop(exp_id, None)
            self.db.vector_store.pop(exp_id, None)

        outcomes_before = len(self.chunk_outcomes)
        status = await super().process_chunk(chunk, doc_meta)

        if previous is not None and exp_id not in self.db.experiments:
            if previous.id == exp_id:
                self.db.experiments[exp_id] = previous
                if previous_vector is not None:
                    self.db.vector_store[exp_id] = previous_vector
                logger.warning(
                    "Re-label produced no experiment for %s; restored previous VSA record",
                    exp_id,
                )
            if len(self.chunk_outcomes) > outcomes_before:
                self.chunk_outcomes.pop()
            self._record_chunk_outcome(doc_meta, chunk, "restored", exp_id)
            return "restored"

        return status


def write_ingestion_report(stats: dict[str, Any], run_id: str | None = None) -> Path:
    """Persist ingest/relabel run summary to ingestion_reports/{run_id}/summary.json."""
    report_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_dir = Path("ingestion_reports") / report_id
    report_dir.mkdir(parents=True, exist_ok=True)
    summary_path = report_dir / "summary.json"
    payload = {
        "run_id": report_id,
        "counts": stats.get("counts", {}),
        "files_indexed_count": stats.get("files_indexed_count", 0),
        "total_chunks_indexed": stats.get("total_chunks_indexed", 0),
        "files_skipped_count": stats.get("files_skipped_count", 0),
        "total_experiments_in_db": stats.get("total_experiments_in_db", 0),
        "chunk_outcomes": stats.get("chunk_outcomes", []),
    }
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary_path


async def run_corpus_relabel_loader(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    target_categories = resolve_target_categories(args.mode)

    if args.archive_url:
        cache_dir = ".cache/hsme_corpus_relabel_loader"
        os.makedirs(cache_dir, exist_ok=True)
        try:
            data_dir = await download_and_extract_yandex_archive(args.archive_url, cache_dir)
        except Exception as exc:
            logger.error("Failed to fetch Yandex Disk archive: %s: %s", type(exc).__name__, exc)
            return 1

    if not os.path.exists(data_dir):
        logger.error("Data directory '%s' not found.", data_dir)
        return 1

    logger.info("Using data directory: %s", data_dir)
    if target_categories:
        logger.info("Target folders: %s", ", ".join(target_categories))

    db_file = args.db_file or os.environ.get("HSME_DATABASE_FILE", ".local/db_state.pkl")
    os.environ["HSME_DATABASE_FILE"] = db_file

    if not args.use_neo4j:
        os.environ["USE_NEO4J"] = "false"

    from backend.repository.neo4j_graph import neo4j_graph

    neo4j_graph.enabled = args.use_neo4j

    try:
        extractor = build_extractor(args)
    except YandexAIStudioConfigError as exc:
        logger.error("LLM config error: %s", exc)
        return 2

    logger.info("Loading vector database from %s...", db_file)
    db = HSMEVectorDatabase(dim=10000)
    db.db_filepath = db_file
    db.load_from_disk(db_file)

    limit = args.max_files if args.max_files is not None else (15 if args.mode == "test" else 999999)
    skip_files = max(0, args.skip_files or 0)
    if args.max_files is None and args.mode == "test" and skip_files > 0:
        limit = max(0, limit - skip_files)
    if args.use_llm:
        concurrency_limit = args.concurrency
        llm_base = args.llm_base_url or resolve_llm_settings(env_file=args.llm_env_file).get("LLM_BASE_URL", "")
        if llm_base and ("openrouter.ai" in llm_base or "proxyapi.ru" in llm_base) and args.concurrency > 3:
            concurrency_limit = 3
            logger.info(
                "Reduced concurrency from %d to %d for external LLM rate limits.",
                args.concurrency,
                concurrency_limit,
            )
    else:
        concurrency_limit = resolve_yandex_concurrency(args.concurrency)
        if concurrency_limit != args.concurrency:
            logger.info(
                "Reduced concurrency from %d to %d for Yandex AI Studio rate limits.",
                args.concurrency,
                concurrency_limit,
            )

    pipeline = RelabelIngestionPipeline(
        db,
        concurrency_limit=concurrency_limit,
        extractor=extractor,
    )

    if args.dry_run:
        logger.info("DRY RUN: Scanning up to %d files in %s...", limit, data_dir)
        if args.clear_neo4j:
            logger.info("DRY RUN: would clear Neo4j graph before re-labeling")
        parser = DocumentParser(target_categories=target_categories) if target_categories else DocumentParser()
        files = parser.scan_directory(data_dir)
        files.sort(key=lambda x: 0 if "Обзоры" in x else (1 if "Статьи" in x else 2))
        if skip_files:
            files = files[skip_files:]
        files = files[:limit]

        total_chunks = 0
        for file_path in files:
            doc = parser.parse_file(file_path)
            if doc and doc["chunks"]:
                total_chunks += len(doc["chunks"])

        logger.info(
            "Dry run complete. Skipped %d file(s). Files to re-label: %d. Chunks: %d.",
            skip_files,
            len(files),
            total_chunks,
        )
        return 0

    if args.clear_neo4j:
        if not neo4j_graph.is_configured:
            logger.error("--clear-neo4j requested but Neo4j is not configured.")
            return 1
        clear_stats = await neo4j_graph.clear_all_async()
        logger.info(
            "Neo4j cleared: nodes=%d relationships=%d",
            clear_stats.get("nodes_deleted", 0),
            clear_stats.get("relationships_deleted", 0),
        )
        from backend.core.config import USE_ASYNC_GRAPH_SYNC
        from backend.repository.migration import run_backfill, run_outbox_backfill
        from backend.services.graph_sync import graph_sync_service

        if USE_ASYNC_GRAPH_SYNC and graph_sync_service.is_async_enabled:
            backfill_stats = await run_outbox_backfill()
            logger.info("Neo4j resync via outbox backfill after clear: %s", backfill_stats)
        else:
            backfill_stats = await run_backfill()
            logger.info("Neo4j resync via direct backfill after clear: %s", backfill_stats)

    if args.use_neo4j and neo4j_graph.is_configured:
        await neo4j_graph.ensure_indexes()

    logger.info(
        "Running re-label ingestion (mode=%s, max_files=%d, skip_files=%d, model=%s)...",
        args.mode,
        limit,
        skip_files,
        extractor.model_id,
    )

    stats = await pipeline.ingest_directory(
        data_dir,
        max_files=limit,
        target_categories=target_categories,
        skip_files=skip_files,
    )

    report_path = write_ingestion_report(stats)
    logger.info("Ingestion report written to %s", report_path)

    logger.info(
        "Re-label complete. Skipped %d file(s). Processed %d files (%d chunks). Total DB size: %d.",
        stats.get("files_skipped_count", 0),
        stats.get("files_indexed_count", 0),
        stats.get("total_chunks_indexed", 0),
        stats.get("total_experiments_in_db", 0),
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-label HSME corpus with YandexGPT 5.1 and optional Neo4j reset.",
    )
    parser.add_argument(
        "--archive-url",
        type=str,
        default=None,
        help=f"Public URL of a Yandex Disk folder/archive (default archive: {DEFAULT_ARCHIVE_URL})",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["test", "prod"],
        default="test",
        help="Run mode: 'test' (limited files) or 'prod' (all files)",
    )
    parser.add_argument("--max-files", type=int, help="Override the maximum number of files to process")
    parser.add_argument(
        "--skip-files",
        type=int,
        default=0,
        help="Skip the first N files in the sorted corpus list (resume after interrupt)",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        help=f"Local corpus root (test default: {TEST_DATA_DIR}/, prod default: {PROD_DATA_DIR}/)",
    )
    parser.add_argument("--db-file", type=str, help="Path to the output pickle file")
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Use LLM_API_KEY / LLM_BASE_URL / LLM_MODEL from .env (OpenRouter, ProxyAPI, etc.)",
    )
    parser.add_argument(
        "--llm-env-file",
        type=str,
        default=".env",
        help="Dotenv file with LLM_* or YANDEX_* credentials",
    )
    parser.add_argument("--llm-api-key", type=str, help="Override LLM_API_KEY")
    parser.add_argument("--llm-base-url", type=str, help="Override LLM_BASE_URL")
    parser.add_argument("--llm-folder-id", type=str, help="Override LLM_FOLDER_ID (Yandex via proxy)")
    parser.add_argument("--llm-model-id", type=str, help="Override LLM_MODEL / LLM_MODEL_ID")
    parser.add_argument("--yandex-api-key", type=str, help="Override YANDEX_API_KEY")
    parser.add_argument("--yandex-folder-id", type=str, help="Override YANDEX_FOLDER_ID")
    parser.add_argument("--yandex-base-url", type=str, help="Override YANDEX_BASE_URL")
    parser.add_argument(
        "--yandex-model",
        type=str,
        default=DEFAULT_MODEL_SLUG,
        help=f"Yandex model slug (default: {DEFAULT_MODEL_SLUG})",
    )
    parser.add_argument(
        "--clear-neo4j",
        action="store_true",
        help="Delete all nodes and relationships in Neo4j before re-labeling",
    )
    parser.add_argument(
        "--no-neo4j",
        action="store_false",
        dest="use_neo4j",
        help="Disable dual-write to Neo4j",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse files and count chunks, but do not call LLM or write to DB",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=YANDEX_DEFAULT_CONCURRENCY,
        help=(
            "Concurrent chunks to process "
            f"(default: {YANDEX_DEFAULT_CONCURRENCY}, max: {YANDEX_SAFE_MAX_CONCURRENCY})"
        ),
    )
    parser.set_defaults(use_neo4j=True)
    args = parser.parse_args(argv)
    return asyncio.run(run_corpus_relabel_loader(args))


if __name__ == "__main__":
    sys.exit(main())
