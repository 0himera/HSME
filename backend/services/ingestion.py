import os
import asyncio
import logging
import re
import time
from typing import List, Dict, Any, Optional

from backend.services.document_parser import CHUNK_VERSION, DocumentParser, slugify_filename
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

MIN_CHUNK_CHARS = int(os.environ.get("NLP_MIN_CHUNK_CHARS", "50"))
SKIP_SHORT_CHUNKS = os.environ.get("NLP_SKIP_SHORT_CHUNKS", "1") != "0"

_PRESENTATION_BOILERPLATE_RE = re.compile(
    r"^(цель\s+курса|результат\s+обучения|результаты\s+обучения|содержание|"
    r"оглавление|спасибо(?:\s+за\s+внимание)?|вопросы\??|контакты|"
    r"thank\s+you|agenda|overview|summary)\s*\.?$",
    re.IGNORECASE,
)
_SLIDE_NUMBER_ONLY_RE = re.compile(r"^[\d\.\,\s\-–—]+$")
_DOMAIN_SIGNAL_RE = re.compile(
    r"(никел|медь|медн|шлак|штейн|выщелач|электроэкстрак|плавк|фильтр|"
    r"сульфат|хлорид|катод|анод|руда|электролит|pH|°C|мг/л|мг/дм|"
    r"А/м|температур|концентрац|процесс|печь|ванн|оборуд|материал|"
    r"раствор|металл|прочност|извлечен|гидрометалл|пирометалл|"
    r"nickel|copper|electrowinning|leaching|electrolyte|slag|smelting|"
    r"furnace|ore|anode|cathode|filter)",
    re.IGNORECASE,
)
_NUMERIC_UNIT_RE = re.compile(
    r"(?:\d+([.,]\d+)?\s*(°C|К|мг/л|мг/дм³|г/л|%|МПа|HB|А/м|pH))"
    r"|(?:pH\s*[:=]?\s*\d+([.,]\d+)?)",
    re.IGNORECASE,
)
_DOMAIN_ENTITY_TYPES = frozenset({"Material", "Process", "Equipment", "Property", "Facility"})


def is_low_signal_chunk(text: str) -> tuple[bool, str]:
    """
    Detect chunks that should skip LLM (short / slide / boilerplate / no domain signal).

    Returns (should_skip, reason_code).
    """
    if not SKIP_SHORT_CHUNKS:
        return False, ""

    stripped = (text or "").strip()
    if len(stripped) < MIN_CHUNK_CHARS:
        return True, "too_short"

    lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
    if not lines:
        return True, "too_short"

    # Drop very short heading-only preamble lines for signal checks.
    body_lines = [ln for ln in lines if len(ln) > 2]
    body = "\n".join(body_lines) if body_lines else stripped

    if _SLIDE_NUMBER_ONLY_RE.match(body):
        return True, "slide_number"

    alnum_tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9]{2,}", body)
    if len(alnum_tokens) < 4:
        return True, "too_few_tokens"

    if len(body_lines) <= 2 and any(_PRESENTATION_BOILERPLATE_RE.match(ln) for ln in body_lines):
        return True, "presentation_boilerplate"

    # Soft domain gate for short fragments (typical slide titles).
    if len(body) < 180:
        if not _DOMAIN_SIGNAL_RE.search(body) and not _NUMERIC_UNIT_RE.search(body):
            return True, "low_domain_signal"

    return False, ""


def has_domain_evidence(entities: List[Dict[str, Any]]) -> bool:
    """True if extraction contains at least one core metallurgy entity type."""
    for ent in entities or []:
        if ent.get("type") in _DOMAIN_ENTITY_TYPES and str(ent.get("value") or "").strip():
            return True
    return False


def _get_neo4j_write_semaphore() -> asyncio.Semaphore:
    global _neo4j_write_semaphore
    if _neo4j_write_semaphore is None:
        _neo4j_write_semaphore = asyncio.Semaphore(1)
    return _neo4j_write_semaphore


def resolve_chunk_version(doc_meta: Optional[Dict[str, Any]] = None, chunk: Optional[Dict[str, Any]] = None) -> str:
    """Resolve ChunkNorris contract version from chunk → doc → default."""
    if chunk and chunk.get("chunk_version"):
        return str(chunk["chunk_version"])
    if doc_meta and doc_meta.get("chunk_version"):
        return str(doc_meta["chunk_version"])
    return CHUNK_VERSION


def make_experiment_id(
    doc_meta: Dict[str, Any],
    chunk_index: int,
    chunk: Optional[Dict[str, Any]] = None,
) -> str:
    """Build a versioned experiment id: EXP-{code|slug}-{chunk_version}-{index:02d}."""
    version = resolve_chunk_version(doc_meta, chunk)
    code = doc_meta.get("code") or "N/A"
    if code != "N/A":
        return f"EXP-{code}-{version}-{chunk_index:02d}"
    slug = doc_meta.get("file_slug") or slugify_filename(doc_meta.get("filename", "unknown"))
    return f"EXP-{slug}-{version}-{chunk_index:02d}"


def chunk_is_sensitive(text: str, skip_reason: Optional[str] = None) -> bool:
    if skip_reason == "moderation":
        return True
    return bool(SENSITIVE_KEYWORDS_RE.search(text))


def summarize_validation_outcomes(outcomes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate failure_class / drop stats for ingestion_reports summary."""
    by_class: Dict[str, int] = {}
    failed = 0
    dropped_entities = 0
    dropped_relations = 0
    samples: List[Dict[str, Any]] = []
    for item in outcomes:
        fc = item.get("failure_class")
        if fc:
            by_class[fc] = by_class.get(fc, 0) + 1
        if item.get("status") in {"validation_failed", "moderation", "empty"}:
            failed += 1
            if len(samples) < 20:
                samples.append(
                    {
                        "experiment_id": item.get("experiment_id"),
                        "file": item.get("file"),
                        "chunk_index": item.get("chunk_index"),
                        "status": item.get("status"),
                        "failure_class": fc,
                        "error_count": item.get("error_count"),
                        "clean_json_preview": item.get("clean_json_preview"),
                        "error_messages": item.get("error_messages"),
                    }
                )
        dropped_entities += int(item.get("dropped_entities") or 0)
        dropped_relations += int(item.get("dropped_relations") or 0)
    return {
        "failure_class_counts": by_class,
        "failed_or_empty_chunks": failed,
        "total_dropped_entities": dropped_entities,
        "total_dropped_relations": dropped_relations,
        "samples": samples,
    }


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
        validation: Optional[Dict[str, Any]] = None,
    ) -> None:
        entry: Dict[str, Any] = {
            "experiment_id": experiment_id,
            "file": doc_meta.get("filename"),
            "chunk_index": chunk.get("index"),
            "status": status,
            "chunk_version": resolve_chunk_version(doc_meta, chunk),
            "content_type": chunk.get("content_type") or "text",
            "section": chunk.get("section"),
        }
        if validation:
            # Keep only compact, serializable diagnostics.
            entry["failure_class"] = validation.get("failure_class")
            entry["error_count"] = validation.get("error_count")
            entry["dropped_entities"] = validation.get("dropped_entities")
            entry["dropped_relations"] = validation.get("dropped_relations")
            entry["raw_entity_count"] = validation.get("raw_entity_count")
            entry["raw_relation_count"] = validation.get("raw_relation_count")
            if validation.get("clean_json_preview"):
                entry["clean_json_preview"] = str(validation["clean_json_preview"])[:240]
            if validation.get("raw_preview"):
                entry["raw_preview"] = str(validation["raw_preview"])[:240]
            if validation.get("error_messages"):
                entry["error_messages"] = list(validation["error_messages"])[:5]
            if validation.get("entity_drop_reasons"):
                entry["entity_drop_reasons"] = list(validation["entity_drop_reasons"])[:5]
            if validation.get("relation_drop_reasons"):
                entry["relation_drop_reasons"] = list(validation["relation_drop_reasons"])[:5]
            if validation.get("attempt") is not None:
                entry["attempt"] = validation.get("attempt")
            if validation.get("skip_reason"):
                entry["skip_reason"] = validation.get("skip_reason")
            if validation.get("low_signal_reason"):
                entry["low_signal_reason"] = validation.get("low_signal_reason")
        self.chunk_outcomes.append(entry)

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
        exp_id = make_experiment_id(doc_meta, chunk["index"], chunk)
        if exp_id in self.db.experiments:
            self._record_chunk_outcome(doc_meta, chunk, "skipped", exp_id)
            return "skipped"

        async with self.semaphore:
            text = chunk["text"]
            skip_low, low_reason = is_low_signal_chunk(text)
            if skip_low:
                self._record_chunk_outcome(
                    doc_meta,
                    chunk,
                    "empty",
                    exp_id,
                    validation={
                        "failure_class": "empty",
                        "skip_reason": "low_signal_prefilter",
                        "low_signal_reason": low_reason,
                    },
                )
                return "empty"

            res = await self.extractor.extract_entities_and_relations(text)
            skip_reason = res.get("_skip_reason")
            validation = res.get("_validation") if isinstance(res.get("_validation"), dict) else None

            if skip_reason == "moderation":
                self._record_chunk_outcome(
                    doc_meta, chunk, "moderation", exp_id, validation=validation
                )
                return "moderation"

            if skip_reason == "validation_failed" or not res.get("entities"):
                status = "validation_failed" if skip_reason else "empty"
                if status == "empty" and validation is None:
                    validation = {"failure_class": "empty"}
                elif status == "validation_failed" and validation is None:
                    validation = {"failure_class": "schema_error"}
                self._record_chunk_outcome(
                    doc_meta, chunk, status, exp_id, validation=validation
                )
                return status

            # Publication/author-only extractions are not domain experiments.
            if not has_domain_evidence(res.get("entities") or []):
                weak_validation = {
                    **(validation or {}),
                    "failure_class": "empty",
                    "skip_reason": "weak_domain_evidence",
                }
                self._record_chunk_outcome(
                    doc_meta, chunk, "empty", exp_id, validation=weak_validation
                )
                return "empty"

            inputs, processes, outputs = self.classify_entities(res["entities"])

            if not inputs and not processes and not outputs:
                empty_validation = validation or {"failure_class": "empty"}
                if empty_validation.get("failure_class") is None:
                    empty_validation = {**empty_validation, "failure_class": "empty"}
                self._record_chunk_outcome(
                    doc_meta, chunk, "empty", exp_id, validation=empty_validation
                )
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

            section_label = chunk.get("section") or "Введение"
            content_type = chunk.get("content_type") or "text"
            version = resolve_chunk_version(doc_meta, chunk)
            exp_name = (
                f"{doc_meta['title']} (Раздел {section_label}, "
                f"Чанк {chunk['index']}, {version}, {content_type})"
            )

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

            self.db.insert_experiment(experiment, auto_save=False)

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

            self._record_chunk_outcome(
                doc_meta, chunk, "ok", exp_id, validation=validation
            )
            return "ok"

    async def ingest_file(self, file_path: str, source_type: str) -> int:
        """Parses a single file, processes all its chunks concurrently, and indexes them."""
        doc = self.parser.parse_file(file_path)
        if not doc or not doc["chunks"]:
            return 0

        doc["source_type"] = source_type

        # Process all chunks concurrently without autosave
        tasks = [self.process_chunk(chunk, doc) for chunk in doc["chunks"]]
        await asyncio.gather(*tasks)
        
        # Save the database once after processing all chunks in the file
        self.db.save_to_disk(self.db.db_filepath, run_in_background=True)
        
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

        # Sort files to put 'Обзоры' and 'Статьи' first (for relabel)
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

            # Parse file metadata and chunks to check if it's already indexed
            doc = parser.parse_file(file)
            if not doc or not doc["chunks"]:
                continue
                
            # Check if there's any new (unindexed) chunk in the file
            has_new_chunks = False
            for chunk in doc["chunks"]:
                exp_id = make_experiment_id(doc, chunk["index"], chunk)
                if exp_id not in self.db.experiments:
                    has_new_chunks = True
                    break
            
            if not has_new_chunks:
                # File is already fully indexed. Skip to allow indexing other files.
                logger.info("Skipping already fully indexed file: %s", os.path.basename(file))
                continue

            logger.info("Indexing [%s] %s...", source_type, os.path.basename(file))
            chunks_count = await self.ingest_file(file, source_type)
            if chunks_count > 0:
                indexed_count += 1
                total_chunks += chunks_count
                indexed_files.append(file)
                if progress_callback:
                    progress_callback(file, chunks_count)

        counts = summarize_chunk_outcomes(self.chunk_outcomes)
        validation_summary = summarize_validation_outcomes(self.chunk_outcomes)

        # Final synchronous persist — background per-file saves can race process exit.
        self.db.save_to_disk(self.db.db_filepath, run_in_background=False)

        return {
            "files_indexed_count": indexed_count,
            "total_chunks_indexed": total_chunks,
            "indexed_files": indexed_files,
            "files_skipped_count": len(skipped_files),
            "total_experiments_in_db": len(self.db.experiments),
            "chunk_outcomes": list(self.chunk_outcomes),
            "counts": counts,
            "validation_summary": validation_summary,
        }


pipeline = IngestionPipeline(db, concurrency_limit=6)
