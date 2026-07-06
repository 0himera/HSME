import os
import asyncio
import logging
import re
import time
from typing import List, Dict, Any, Optional

from backend.services.document_parser import DocumentParser, slugify_filename
from backend.services.nlp_extractor import NLPExtractor
from backend.core.models import Entity, Experiment, Relation
from backend.core.config import USE_ASYNC_GRAPH_SYNC, ASYNC_GRAPH_SYNC_REQUIRED
from backend.repository.database import HSMEVectorDatabase, db
from backend.repository.neo4j_graph import neo4j_graph
from backend.services.graph_sync import graph_sync_service

logger = logging.getLogger(__name__)

_neo4j_write_semaphore: asyncio.Semaphore | None = None

SENSITIVE_KEYWORDS_RE = re.compile(
    r"\b(U|Pu|UF6|уран|плутоний|plutonium|uranium)\b",
    re.IGNORECASE,
)

CHUNK_OUTCOME_STATUSES = frozenset(
    {
        "ok",
        "skipped",
        "restored",
        "validation_failed",
        "moderation",
        "empty",
        "graph_sync_failed",
        "graph_sync_deferred",
    }
)


def _get_neo4j_write_semaphore() -> asyncio.Semaphore:
    global _neo4j_write_semaphore
    if _neo4j_write_semaphore is None:
        _neo4j_write_semaphore = asyncio.Semaphore(1)
    return _neo4j_write_semaphore


def make_experiment_id(doc_meta: Dict[str, Any], chunk_index: int) -> str:
    """Build a stable experiment id from document code or file slug."""
    code = doc_meta.get("code") or "N/A"
    if code != "N/A":
        return f"EXP-{code}-{chunk_index:02d}"
    slug = doc_meta.get("file_slug") or slugify_filename(doc_meta.get("filename", "unknown"))
    return f"EXP-{slug}-{chunk_index:02d}"


def chunk_is_sensitive(text: str, skip_reason: Optional[str] = None) -> bool:
    if skip_reason == "moderation":
        return True
    return bool(SENSITIVE_KEYWORDS_RE.search(text))


def summarize_chunk_outcomes(outcomes: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {status: 0 for status in CHUNK_OUTCOME_STATUSES}
    for item in outcomes:
        status = item.get("status", "empty")
        if status in counts:
            counts[status] += 1
    return counts


class IngestionPipeline:
    def __init__(self, db: HSMEVectorDatabase, concurrency_limit: int = 8, extractor: NLPExtractor = None):
        self.db = db
        self.parser = DocumentParser()
        self.extractor = extractor if extractor is not None else NLPExtractor()
        self.semaphore = asyncio.Semaphore(concurrency_limit)
        self.chunk_outcomes: List[Dict[str, Any]] = []

    def _record_chunk_outcome(
        self,
        doc_meta: Dict[str, Any],
        chunk: Dict[str, Any],
        status: str,
        experiment_id: Optional[str] = None,
    ) -> None:
        self.chunk_outcomes.append(
            {
                "experiment_id": experiment_id,
                "file": doc_meta.get("filename"),
                "chunk_index": chunk.get("index"),
                "status": status,
            }
        )

    def guess_geography(self, text: str, filename: str) -> str:
        """Guesses the geographical context of the document (RU or Global)."""
        combined = (text + " " + filename).lower()
        ru_keywords = ["россия", "кольский", "гмк", "комсомольский", "кайерканский", "норильск", "сибирь", "урал", "черняевск"]
        global_keywords = ["australia", "caledonia", "chile", "harbour", "glencore", "eramet", "outotec", "valegoro"]

        ru_score = sum(1 for kw in ru_keywords if kw in combined)
        global_score = sum(1 for kw in global_keywords if kw in combined)

        if ru_score > global_score:
            return "RU"
        elif global_score > ru_score:
            return "Global"
        return "RU" if any(c in combined for c in "абвгдежзийклмнопрстуфхцчшщъыьэюя") else "Global"

    def classify_entities(self, entities: List[Dict[str, str]]) -> tuple[List[Entity], List[Entity], List[Entity]]:
        """Classifies extracted flat entities into inputs, processes, and outputs for the Experiment model."""
        inputs = []
        processes = []
        outputs = []

        for ent in entities:
            e_type = ent.get("type", "Property")
            e_val = ent.get("value", "").strip()
            if not e_val:
                continue

            entity_obj = Entity(type=e_type, value=e_val)

            if e_type in ["Material", "Facility"]:
                if any(kw in e_val.lower() for kw in ["катод", "осадок", "раствор ni-cu", "шлам", "хвосты", "продукт", "выход"]):
                    outputs.append(entity_obj)
                else:
                    inputs.append(entity_obj)
            elif e_type in ["Process", "Equipment"]:
                processes.append(entity_obj)
            elif e_type == "Property":
                if any(kw in e_val.lower() for kw in ["выход по току", "светлость", "извлечение", "чистота", "содержание", "дефект", "производительность"]):
                    outputs.append(entity_obj)
                else:
                    inputs.append(entity_obj)
            else:
                inputs.append(entity_obj)

        return inputs, processes, outputs

    async def process_chunk(self, chunk: Dict[str, Any], doc_meta: Dict[str, Any]) -> str:
        """Processes a single text chunk; returns outcome status for manifest."""
        exp_id = make_experiment_id(doc_meta, chunk["index"])
        if exp_id in self.db.experiments:
            self._record_chunk_outcome(doc_meta, chunk, "skipped", exp_id)
            return "skipped"

        async with self.semaphore:
            text = chunk["text"]
            res = await self.extractor.extract_entities_and_relations(text)
            skip_reason = res.get("_skip_reason")

            if skip_reason == "moderation":
                self._record_chunk_outcome(doc_meta, chunk, "moderation", exp_id)
                return "moderation"

            if skip_reason == "validation_failed" or not res.get("entities"):
                status = "validation_failed" if skip_reason else "empty"
                self._record_chunk_outcome(doc_meta, chunk, status, exp_id)
                return status

            inputs, processes, outputs = self.classify_entities(res["entities"])

            if not inputs and not processes and not outputs:
                self._record_chunk_outcome(doc_meta, chunk, "empty", exp_id)
                return "empty"

            publication_title = doc_meta["title"]
            inputs.append(Entity(type="Publication", value=publication_title))
            for auth in doc_meta["authors"]:
                if auth != "Не указан":
                    processes.append(Entity(type="Expert", value=auth))

            geography = self.guess_geography(text, doc_meta["filename"])

            relations = []
            for rel in res.get("relations", []):
                source = rel.get("source", "").strip()
                rel_type = rel.get("type", "").strip()
                target = rel.get("target", "").strip()
                if source and rel_type and target:
                    relations.append(Relation(source=source, type=rel_type, target=target))

            exp_name = f"{doc_meta['title']} (Раздел {chunk['section'] or 'Введение'}, Чанк {chunk['index']})"

            experiment = Experiment(
                id=exp_id,
                name=exp_name,
                input_entities=inputs,
                process_entities=processes,
                output_entities=outputs,
                relations=relations,
                evidence=[doc_meta["filename"]],
                confidence=0.95,
                year=doc_meta["year"],
                geography=geography,
                source_type=doc_meta["source_type"],
                is_sensitive=chunk_is_sensitive(text, skip_reason),
            )

            self.db.insert_experiment(experiment)

            if neo4j_graph.is_configured:
                if USE_ASYNC_GRAPH_SYNC and graph_sync_service.is_async_enabled:
                    enqueue_start = time.perf_counter()
                    try:
                        event_id = await graph_sync_service.enqueue_experiment_upsert(
                            experiment,
                            source="ingestion",
                        )
                        enqueue_ms = (time.perf_counter() - enqueue_start) * 1000
                        logger.info(
                            "Graph sync enqueued experiment=%s event_id=%s enqueue_ms=%.1f",
                            experiment.id,
                            event_id,
                            enqueue_ms,
                        )
                    except Exception as exc:
                        enqueue_ms = (time.perf_counter() - enqueue_start) * 1000
                        logger.warning(
                            "Graph sync enqueue failed experiment=%s enqueue_ms=%.1f error=%s",
                            experiment.id,
                            enqueue_ms,
                            exc.__class__.__name__,
                        )
                        if ASYNC_GRAPH_SYNC_REQUIRED:
                            self._record_chunk_outcome(
                                doc_meta, chunk, "graph_sync_failed", exp_id
                            )
                            raise
                        self._record_chunk_outcome(
                            doc_meta, chunk, "graph_sync_deferred", exp_id
                        )
                        return "graph_sync_deferred"
                else:
                    neo_start = time.perf_counter()
                    try:
                        async with _get_neo4j_write_semaphore():
                            await neo4j_graph.insert_experiment_async(experiment)
                    except Exception as exc:
                        neo_ms = (time.perf_counter() - neo_start) * 1000
                        logger.warning(
                            "Neo4j dual-write skipped experiment=%s overhead_ms=%.1f error=%s",
                            experiment.id,
                            neo_ms,
                            exc.__class__.__name__,
                        )

            self._record_chunk_outcome(doc_meta, chunk, "ok", exp_id)
            return "ok"

    async def ingest_file(self, file_path: str, source_type: str) -> int:
        """Parses a single file, processes all its chunks concurrently, and indexes them."""
        doc = self.parser.parse_file(file_path)
        if not doc or not doc["chunks"]:
            return 0

        doc["source_type"] = source_type

        tasks = [self.process_chunk(chunk, doc) for chunk in doc["chunks"]]
        await asyncio.gather(*tasks)
        return len(doc["chunks"])

    async def ingest_directory(
        self,
        base_dir: str,
        max_files: int = 15,
        progress_callback=None,
        target_categories: List[str] | None = None,
        skip_files: int = 0,
    ) -> Dict[str, Any]:
        """Scans directory and indexes up to max_files of high-priority research documents."""
        self.chunk_outcomes = []

        parser = DocumentParser(target_categories=target_categories) if target_categories else self.parser
        files = parser.scan_directory(base_dir)

        files.sort(key=lambda x: 0 if "Обзоры" in x else (1 if "Статьи" in x else 2))

        skipped_files: List[str] = []
        if skip_files > 0:
            skipped_files = files[:skip_files]
            files = files[skip_files:]
            preview = ", ".join(os.path.basename(path) for path in skipped_files[:5])
            if len(skipped_files) > 5:
                preview += ", ..."
            logger.info(
                "Skipping first %d file(s)%s",
                skip_files,
                f": {preview}" if preview else "",
            )

        indexed_count = 0
        total_chunks = 0
        indexed_files = []

        for file in files:
            if indexed_count >= max_files:
                break

            source_type = "Статья"
            if "Обзоры" in file:
                source_type = "Обзор"
            elif "Доклады" in file:
                source_type = "Доклад"
            elif "Журналы" in file:
                source_type = "Журнал"

            logger.info("Indexing [%s] %s...", source_type, os.path.basename(file))
            chunks_count = await self.ingest_file(file, source_type)
            if chunks_count > 0:
                indexed_count += 1
                total_chunks += chunks_count
                indexed_files.append(file)
                if progress_callback:
                    progress_callback(file, chunks_count)

        counts = summarize_chunk_outcomes(self.chunk_outcomes)

        return {
            "files_indexed_count": indexed_count,
            "total_chunks_indexed": total_chunks,
            "indexed_files": indexed_files,
            "files_skipped_count": len(skipped_files),
            "total_experiments_in_db": len(self.db.experiments),
            "chunk_outcomes": list(self.chunk_outcomes),
            "counts": counts,
        }


pipeline = IngestionPipeline(db, concurrency_limit=6)
