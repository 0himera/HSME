"""Tests for async graph sync service, Redis transport, and ingestion integration."""

from __future__ import annotations

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.graph_sync_events import GraphSyncEvent
from backend.core.models import Entity, Experiment
from backend.repository.database import HSMEVectorDatabase
from backend.repository.ingestion_outbox import IngestionOutboxRepository
from backend.services.graph_sync import GraphSyncService
from backend.services.ingestion import IngestionPipeline
from backend.services.redis_streams import RedisStreamsClient


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
def outbox_path(tmp_path):
    return str(tmp_path / "test_outbox.db")


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


def test_redis_publish_dry_run():
    client = RedisStreamsClient(enabled=True, dry_run=True)
    message_id = client.publish({"event_id": "evt-1", "payload": "{}"})
    assert message_id.startswith("dry-run-")


def test_graph_sync_publish_pending_batch(outbox_path, monkeypatch):
    monkeypatch.setenv("USE_ASYNC_GRAPH_SYNC", "true")
    monkeypatch.setenv("USE_NEO4J", "true")

    repo = IngestionOutboxRepository(db_path=outbox_path)
    repo.ensure_schema()
    event = GraphSyncEvent.from_experiment(
        Experiment(
            id="EXP-GS-01",
            name="Test",
            input_entities=[Entity(type="Material", value="Ni")],
            process_entities=[],
            output_entities=[],
        ),
        source="ingestion",
    )
    repo.enqueue(event)

    service = GraphSyncService()
    service._schema_ready = True

    mock_redis = MagicMock()
    mock_redis.is_configured = True
    mock_redis.publish = MagicMock(return_value="1700000000000-0")

    with patch("backend.services.graph_sync.ingestion_outbox", repo), \
         patch("backend.services.graph_sync.redis_streams", mock_redis), \
         patch("backend.services.graph_sync.USE_ASYNC_GRAPH_SYNC", True), \
         patch("backend.services.graph_sync.USE_NEO4J", True), \
         patch("backend.services.graph_sync.neo4j_graph") as mock_graph:
        mock_graph.is_configured = True
        stats = service.publish_pending_batch(limit=10)

    assert stats["published"] == 1
    row = repo.get_event(event.event_id)
    assert row["status"] == "published"
    mock_redis.publish.assert_called_once()


@pytest.mark.asyncio
async def test_process_chunk_async_mode_enqueues_not_neo4j(isolated_db, outbox_path, monkeypatch):
    monkeypatch.setenv("USE_ASYNC_GRAPH_SYNC", "true")
    pipeline = IngestionPipeline(isolated_db, concurrency_limit=1)
    pipeline.extractor.extract_entities_and_relations = AsyncMock(
        return_value={
            "entities": [
                {"type": "Material", "value": "Nickel electrolyte"},
                {"type": "Process", "value": "Electrowinning"},
            ],
            "relations": [],
        }
    )

    mock_service = MagicMock()
    mock_service.is_async_enabled = True
    mock_service.enqueue_experiment_upsert = AsyncMock(return_value="evt-123")

    with patch("backend.services.ingestion.USE_ASYNC_GRAPH_SYNC", True), \
         patch("backend.services.ingestion.graph_sync_service", mock_service), \
         patch("backend.services.ingestion.neo4j_graph") as mock_graph:
        mock_graph.is_configured = True
        mock_graph.insert_experiment_async = AsyncMock(return_value=True)

        await pipeline.process_chunk(_chunk(), _doc_meta())

    assert len(isolated_db.experiments) == 1
    mock_service.enqueue_experiment_upsert.assert_awaited_once()
    mock_graph.insert_experiment_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_chunk_sync_fallback_when_async_disabled(isolated_db):
    pipeline = IngestionPipeline(isolated_db, concurrency_limit=1)
    pipeline.extractor.extract_entities_and_relations = AsyncMock(
        return_value={
            "entities": [
                {"type": "Material", "value": "Nickel electrolyte"},
                {"type": "Process", "value": "Electrowinning"},
            ],
            "relations": [],
        }
    )

    with patch("backend.services.ingestion.USE_ASYNC_GRAPH_SYNC", False), \
         patch("backend.services.ingestion.graph_sync_service") as mock_service, \
         patch("backend.services.ingestion.neo4j_graph") as mock_graph:
        mock_service.is_async_enabled = False
        mock_graph.is_configured = True
        mock_graph.insert_experiment_async = AsyncMock(return_value=True)

        await pipeline.process_chunk(_chunk(), _doc_meta())

    mock_graph.insert_experiment_async.assert_awaited_once()
    mock_service.enqueue_experiment_upsert.assert_not_called()


@pytest.mark.asyncio
async def test_worker_process_message_acks_on_success(outbox_path):
    from backend.workers import neo4j_consumer

    event = GraphSyncEvent.from_experiment(
        Experiment(
            id="EXP-WK-01",
            name="Worker test",
            input_entities=[Entity(type="Material", value="Cu")],
            process_entities=[],
            output_entities=[],
        ),
        source="ingestion",
    )
    repo = IngestionOutboxRepository(db_path=outbox_path)
    repo.ensure_schema()
    repo.enqueue(event)
    repo.mark_published(event.event_id, "1700000000000-0")

    fields = event.to_stream_fields()
    mock_redis = MagicMock()
    mock_redis.ack = MagicMock()

    with patch("backend.workers.neo4j_consumer.ingestion_outbox", repo), \
         patch("backend.workers.neo4j_consumer.redis_streams", mock_redis), \
         patch("backend.workers.neo4j_consumer.neo4j_graph") as mock_graph:
        mock_graph.is_configured = True
        mock_graph.insert_experiment_async = AsyncMock(return_value=True)

        ok = await neo4j_consumer.process_message("1700000000000-0", fields)

    assert ok is True
    assert repo.get_event(event.event_id)["status"] == "acked"
    mock_redis.ack.assert_called_once_with("1700000000000-0")


def test_replay_outbox_cli_dry_run(outbox_path, monkeypatch, capsys):
    monkeypatch.setenv("OUTBOX_DB_PATH", outbox_path)
    repo = IngestionOutboxRepository(db_path=outbox_path)
    repo.ensure_schema()
    event = GraphSyncEvent.from_experiment(
        Experiment(
            id="EXP-RL-01",
            name="Replay",
            input_entities=[Entity(type="Material", value="Fe")],
            process_entities=[],
            output_entities=[],
        ),
        source="ingestion",
    )
    repo.enqueue(event)

    with patch("backend.repository.replay_outbox.ingestion_outbox", repo), \
         patch("backend.repository.replay_outbox.graph_sync_service") as mock_service:
        mock_service.ensure_schema = MagicMock()
        mock_service.publish_pending_batch = MagicMock(return_value={"published": 0, "failed": 0})

        from backend.repository.replay_outbox import main

        code = main(["--dry-run"])
        output = capsys.readouterr().out

    assert code == 0
    assert "outbox_pending" in output


def test_graph_sync_required_raises_when_redis_down(monkeypatch, outbox_path):
    monkeypatch.setenv("USE_ASYNC_GRAPH_SYNC", "true")
    monkeypatch.setenv("ASYNC_GRAPH_SYNC_REQUIRED", "true")

    service = GraphSyncService()
    repo = IngestionOutboxRepository(db_path=outbox_path)
    repo.ensure_schema()
    service._schema_ready = True

    mock_redis = MagicMock()
    mock_redis.ping = MagicMock(return_value=False)
    mock_redis.is_configured = True

    with patch("backend.services.graph_sync.ingestion_outbox", repo), \
         patch("backend.services.graph_sync.redis_streams", mock_redis), \
         patch("backend.services.graph_sync.USE_ASYNC_GRAPH_SYNC", True), \
         patch("backend.services.graph_sync.USE_NEO4J", True), \
         patch("backend.services.graph_sync.ASYNC_GRAPH_SYNC_REQUIRED", True), \
         patch("backend.services.graph_sync.neo4j_graph") as mock_graph:
        mock_graph.is_configured = True
        with pytest.raises(RuntimeError, match="Redis is unavailable"):
            service._check_broker_required()


def test_bad_payload_marks_failed_and_acks():
    from backend.workers import neo4j_consumer

    repo = MagicMock()
    mock_redis = MagicMock()

    with patch("backend.workers.neo4j_consumer.ingestion_outbox", repo), \
         patch("backend.workers.neo4j_consumer.redis_streams", mock_redis):
        ok = asyncio.run(
            neo4j_consumer.process_message(
                "1-0",
                {
                    "event_id": "bad-evt",
                    "event_type": "experiment_upsert",
                    "experiment_id": "EXP-BAD",
                    "payload_version": "1",
                    "source": "ingestion",
                    "occurred_at": "2026-01-01T00:00:00+00:00",
                    "payload": "{not-json",
                },
            )
        )

    assert ok is False
    repo.mark_failed.assert_called_once()
    mock_redis.ack.assert_called_once_with("1-0")


@pytest.mark.asyncio
async def test_strict_mode_process_chunk_raises_on_enqueue_failure(isolated_db):
    pipeline = IngestionPipeline(isolated_db, concurrency_limit=1)
    pipeline.extractor.extract_entities_and_relations = AsyncMock(
        return_value={
            "entities": [
                {"type": "Material", "value": "Nickel electrolyte"},
                {"type": "Process", "value": "Electrowinning"},
            ],
            "relations": [],
        }
    )

    mock_service = MagicMock()
    mock_service.is_async_enabled = True
    mock_service.enqueue_experiment_upsert = AsyncMock(
        side_effect=RuntimeError("Redis is unavailable")
    )

    with patch("backend.services.ingestion.USE_ASYNC_GRAPH_SYNC", True), \
         patch("backend.services.ingestion.ASYNC_GRAPH_SYNC_REQUIRED", True), \
         patch("backend.services.ingestion.graph_sync_service", mock_service), \
         patch("backend.services.ingestion.neo4j_graph") as mock_graph:
        mock_graph.is_configured = True
        with pytest.raises(RuntimeError, match="Redis is unavailable"):
            await pipeline.process_chunk(_chunk(), _doc_meta())

    assert len(isolated_db.experiments) == 1
    outcomes = pipeline.chunk_outcomes
    assert any(o.get("status") == "graph_sync_failed" for o in outcomes)


def test_redis_reclaim_pending_uses_xautoclaim():
    client = RedisStreamsClient(enabled=True, dry_run=False)
    mock_redis = MagicMock()
    mock_redis.xautoclaim = MagicMock(
        return_value=(
            "0-0",
            [("1700000000000-0", {"event_id": "evt-1", "payload": "{}"})],
            [],
        )
    )
    client._client = mock_redis

    with patch.object(client, "ensure_consumer_group"):
        reclaimed = client.reclaim_pending("worker-1", count=5, min_idle_ms=1000)

    assert len(reclaimed) == 1
    assert reclaimed[0][0] == "1700000000000-0"
    mock_redis.xautoclaim.assert_called_once()


@pytest.mark.asyncio
async def test_worker_recovery_reclaims_published_not_acked(outbox_path):
    from backend.workers import neo4j_consumer

    event = GraphSyncEvent.from_experiment(
        Experiment(
            id="EXP-RC-01",
            name="Recovery test",
            input_entities=[Entity(type="Material", value="Ni")],
            process_entities=[],
            output_entities=[],
        ),
        source="ingestion",
    )
    repo = IngestionOutboxRepository(db_path=outbox_path)
    repo.ensure_schema()
    repo.enqueue(event)
    repo.mark_published(event.event_id, "1700000000000-0")
    assert repo.get_metrics()["outbox_published_not_acked"] == 1

    fields = event.to_stream_fields()
    mock_redis = MagicMock()
    mock_redis.reclaim_pending = MagicMock(return_value=[("1700000000000-0", fields)])
    mock_redis.read_group = MagicMock(return_value=[])
    mock_redis.ack = MagicMock()

    with patch("backend.workers.neo4j_consumer.ingestion_outbox", repo), \
         patch("backend.workers.neo4j_consumer.redis_streams", mock_redis), \
         patch("backend.workers.neo4j_consumer.graph_sync_service") as mock_gs, \
         patch("backend.workers.neo4j_consumer.neo4j_graph") as mock_graph:
        mock_gs.ensure_schema = MagicMock()
        mock_gs.is_async_enabled = True
        mock_gs.publish_pending_batch = MagicMock(return_value={"published": 0, "failed": 0})
        mock_graph.is_configured = True
        mock_graph.ensure_indexes = AsyncMock()
        mock_graph.insert_experiment_async = AsyncMock(return_value=True)
        mock_redis.ping = MagicMock(return_value=True)

        code = await neo4j_consumer.run_consumer_loop(
            consumer_name="worker-recovery",
            batch_size=10,
            once=True,
            idle_sleep_s=0.01,
        )

    assert code == 0
    assert repo.get_event(event.event_id)["status"] == "acked"
    assert repo.get_metrics()["outbox_published_not_acked"] == 0
    mock_redis.reclaim_pending.assert_called_once()
    mock_redis.ack.assert_called_once_with("1700000000000-0")


@pytest.mark.asyncio
async def test_worker_neo4j_failure_keeps_published_not_republished(outbox_path, monkeypatch):
    from backend.repository.ingestion_outbox import STATUS_PUBLISHED
    from backend.workers import neo4j_consumer

    event = GraphSyncEvent.from_experiment(
        Experiment(
            id="EXP-NF-01",
            name="Neo4j fail",
            input_entities=[Entity(type="Material", value="Cu")],
            process_entities=[],
            output_entities=[],
        ),
        source="ingestion",
    )
    repo = IngestionOutboxRepository(db_path=outbox_path)
    repo.ensure_schema()
    repo.enqueue(event)
    repo.mark_published(event.event_id, "1700000000000-0")

    fields = event.to_stream_fields()
    mock_redis = MagicMock()

    with patch("backend.workers.neo4j_consumer.ingestion_outbox", repo), \
         patch("backend.workers.neo4j_consumer.redis_streams", mock_redis), \
         patch("backend.workers.neo4j_consumer.neo4j_graph") as mock_graph:
        mock_graph.is_configured = True
        mock_graph.insert_experiment_async = AsyncMock(return_value=False)

        ok = await neo4j_consumer.process_message("1700000000000-0", fields)

    assert ok is False
    row = repo.get_event(event.event_id)
    assert row["status"] == STATUS_PUBLISHED
    assert row["attempts"] == 1
    mock_redis.ack.assert_not_called()
    assert len(repo.list_pending()) == 0


@pytest.mark.integration
def test_redis_integration_publish_reclaim_ack(monkeypatch):
    """Smoke with real Redis when available locally."""
    import redis

    try:
        raw = redis.Redis.from_url("redis://127.0.0.1:6379/0", socket_connect_timeout=1)
        raw.ping()
    except Exception:
        pytest.skip("Local Redis unavailable")

    stream_key = "hsme:test:graph_sync"
    group = "hsme-test-workers"
    raw.delete(stream_key)
    try:
        raw.xgroup_create(stream_key, group, id="0", mkstream=True)
    except redis.ResponseError:
        pass

    client = RedisStreamsClient(
        enabled=True,
        dry_run=False,
        stream_key=stream_key,
        consumer_group=group,
    )
    message_id = client.publish({"event_id": "evt-int", "payload": "{}"})
    assert message_id

    read = client.read_group("worker-a", count=1, block_ms=100)
    assert len(read) == 1
    assert read[0][0] == message_id

    reclaimed = client.reclaim_pending("worker-b", count=1, min_idle_ms=0)
    assert len(reclaimed) == 1
    assert reclaimed[0][0] == message_id

    client.ack(message_id)
    raw.delete(stream_key)


@pytest.mark.asyncio
async def test_non_strict_enqueue_failure_records_graph_sync_deferred(isolated_db):
    pipeline = IngestionPipeline(isolated_db, concurrency_limit=1)
    pipeline.extractor.extract_entities_and_relations = AsyncMock(
        return_value={
            "entities": [
                {"type": "Material", "value": "Nickel electrolyte"},
                {"type": "Process", "value": "Electrowinning"},
            ],
            "relations": [],
        }
    )

    mock_service = MagicMock()
    mock_service.is_async_enabled = True
    mock_service.enqueue_experiment_upsert = AsyncMock(
        side_effect=RuntimeError("Redis is unavailable")
    )

    with patch("backend.services.ingestion.USE_ASYNC_GRAPH_SYNC", True), \
         patch("backend.services.ingestion.ASYNC_GRAPH_SYNC_REQUIRED", False), \
         patch("backend.services.ingestion.graph_sync_service", mock_service), \
         patch("backend.services.ingestion.neo4j_graph") as mock_graph:
        mock_graph.is_configured = True
        status = await pipeline.process_chunk(_chunk(), _doc_meta())

    assert status == "graph_sync_deferred"
    assert any(o.get("status") == "graph_sync_deferred" for o in pipeline.chunk_outcomes)


@pytest.mark.asyncio
async def test_worker_requeues_stale_published_at_loop_start(outbox_path, monkeypatch):
    from backend.workers import neo4j_consumer

    repo = IngestionOutboxRepository(db_path=outbox_path)
    repo.ensure_schema()
    mock_redis = MagicMock()
    mock_redis.ping = MagicMock(return_value=True)
    mock_redis.reclaim_pending = MagicMock(return_value=[])
    mock_redis.read_group = MagicMock(return_value=[])

    with patch("backend.workers.neo4j_consumer.ingestion_outbox", repo), \
         patch("backend.workers.neo4j_consumer.redis_streams", mock_redis), \
         patch("backend.workers.neo4j_consumer.graph_sync_service") as mock_gs, \
         patch("backend.workers.neo4j_consumer.neo4j_graph") as mock_graph, \
         patch.object(repo, "requeue_stale_published", return_value=2) as mock_requeue:
        mock_gs.ensure_schema = MagicMock()
        mock_gs.is_async_enabled = True
        mock_gs.publish_pending_batch = MagicMock(return_value={"published": 0, "failed": 0})
        mock_graph.is_configured = True
        mock_graph.ensure_indexes = AsyncMock()

        code = await neo4j_consumer.run_consumer_loop(
            consumer_name="worker-stale",
            batch_size=5,
            once=True,
            idle_sleep_s=0.01,
        )

    assert code == 0
    mock_requeue.assert_called_once()


@pytest.mark.asyncio
async def test_outbox_backfill_enqueues_orphans_only(isolated_db, outbox_path, monkeypatch):
    from backend.repository.migration import run_outbox_backfill

    exp = Experiment(
        id="EXP-BF-01",
        name="Backfill",
        input_entities=[Entity(type="Material", value="Ni")],
        process_entities=[],
        output_entities=[],
    )
    isolated_db.insert_experiment(exp)

    repo = IngestionOutboxRepository(db_path=outbox_path)
    repo.ensure_schema()

    mock_service = MagicMock()
    mock_service.is_async_enabled = True
    mock_service.ensure_schema = MagicMock()
    mock_service.enqueue_experiment_upsert = AsyncMock(return_value="evt-bf")

    with patch("backend.repository.migration.db", isolated_db), \
         patch("backend.repository.migration.ingestion_outbox", repo), \
         patch("backend.repository.migration.graph_sync_service", mock_service):
        stats = await run_outbox_backfill(dry_run=False)

    assert stats["candidates"] == 1
    assert stats["enqueued"] == 1
    mock_service.enqueue_experiment_upsert.assert_awaited_once()


def test_resolve_graph_enrichment_status_sync_pending():
    from backend.routers.search import _resolve_graph_enrichment_status

    status, lag_hint = _resolve_graph_enrichment_status(
        neo4j_configured=True,
        has_results=True,
        graph_context={"experts": [], "publications": [], "contradictions": [], "paths": []},
        sync_state={"has_lag": True, "pending_count": 1, "published_count": 0},
    )
    assert status == "sync_pending"
    assert lag_hint is True
