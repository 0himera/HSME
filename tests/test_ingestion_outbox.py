"""Tests for SQLite graph sync outbox."""

from __future__ import annotations

import os
import tempfile

import pytest

from backend.core.graph_sync_events import GraphSyncEvent
from backend.core.models import Entity, Experiment
from backend.repository.ingestion_outbox import (
    STATUS_ACKED,
    STATUS_DEAD_LETTER,
    STATUS_PENDING,
    STATUS_PUBLISHED,
    IngestionOutboxRepository,
)


@pytest.fixture
def outbox_repo():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = IngestionOutboxRepository(db_path=path)
    repo.ensure_schema()
    yield repo
    if os.path.exists(path):
        os.remove(path)


def _experiment(exp_id: str = "EXP-TEST-01") -> Experiment:
    return Experiment(
        id=exp_id,
        name="Test",
        input_entities=[Entity(type="Material", value="Nickel")],
        process_entities=[],
        output_entities=[],
    )


def test_enqueue_and_lifecycle(outbox_repo):
    event = GraphSyncEvent.from_experiment(_experiment(), source="ingestion")
    outbox_repo.enqueue(event)

    pending = outbox_repo.list_pending()
    assert len(pending) == 1
    assert pending[0]["status"] == STATUS_PENDING

    outbox_repo.mark_published(event.event_id, "1700000000000-0")
    row = outbox_repo.get_event(event.event_id)
    assert row["status"] == STATUS_PUBLISHED
    assert row["redis_message_id"] == "1700000000000-0"

    outbox_repo.mark_acked(event.event_id)
    row = outbox_repo.get_event(event.event_id)
    assert row["status"] == STATUS_ACKED


def test_enqueue_is_idempotent_on_event_id(outbox_repo):
    event = GraphSyncEvent.from_experiment(_experiment(), source="ingestion")
    outbox_repo.enqueue(event)
    outbox_repo.enqueue(event)
    assert len(outbox_repo.list_pending()) == 1


def test_mark_failed_moves_to_dead_letter_after_max_attempts(outbox_repo, monkeypatch):
    monkeypatch.setattr("backend.repository.ingestion_outbox.OUTBOX_MAX_ATTEMPTS", 2)
    event = GraphSyncEvent.from_experiment(_experiment("EXP-FAIL-01"), source="ingestion")
    outbox_repo.enqueue(event)

    outbox_repo.mark_failed(event.event_id, "redis_down")
    row = outbox_repo.get_event(event.event_id)
    assert row["status"] == STATUS_PENDING
    assert row["attempts"] == 1

    outbox_repo.mark_failed(event.event_id, "redis_down")
    row = outbox_repo.get_event(event.event_id)
    assert row["status"] == STATUS_DEAD_LETTER
    assert row["attempts"] == 2


def test_requeue_dead_letters(outbox_repo, monkeypatch):
    monkeypatch.setattr("backend.repository.ingestion_outbox.OUTBOX_MAX_ATTEMPTS", 1)
    event = GraphSyncEvent.from_experiment(_experiment("EXP-DL-01"), source="ingestion")
    outbox_repo.enqueue(event)
    outbox_repo.mark_failed(event.event_id, "error")
    assert outbox_repo.get_event(event.event_id)["status"] == STATUS_DEAD_LETTER

    count = outbox_repo.requeue_dead_letters()
    assert count == 1
    assert outbox_repo.get_event(event.event_id)["status"] == STATUS_PENDING


def test_mark_consume_failed_keeps_published(outbox_repo, monkeypatch):
    monkeypatch.setattr("backend.repository.ingestion_outbox.OUTBOX_MAX_ATTEMPTS", 3)
    event = GraphSyncEvent.from_experiment(_experiment("EXP-CF-01"), source="ingestion")
    outbox_repo.enqueue(event)
    outbox_repo.mark_published(event.event_id, "1700000000000-0")

    status = outbox_repo.mark_consume_failed(event.event_id, "neo4j_insert_failed")
    row = outbox_repo.get_event(event.event_id)
    assert status == STATUS_PUBLISHED
    assert row["status"] == STATUS_PUBLISHED
    assert row["attempts"] == 1


def test_mark_consume_failed_dead_letters_after_max_attempts(outbox_repo, monkeypatch):
    monkeypatch.setattr("backend.repository.ingestion_outbox.OUTBOX_MAX_ATTEMPTS", 2)
    event = GraphSyncEvent.from_experiment(_experiment("EXP-CF-02"), source="ingestion")
    outbox_repo.enqueue(event)
    outbox_repo.mark_published(event.event_id, "1700000000000-0")

    outbox_repo.mark_consume_failed(event.event_id, "neo4j_insert_failed")
    status = outbox_repo.mark_consume_failed(event.event_id, "neo4j_insert_failed")
    assert status == STATUS_DEAD_LETTER
    assert outbox_repo.get_event(event.event_id)["status"] == STATUS_DEAD_LETTER


def test_get_metrics(outbox_repo):
    event = GraphSyncEvent.from_experiment(_experiment(), source="ingestion")
    outbox_repo.enqueue(event)
    metrics = outbox_repo.get_metrics()
    assert metrics["outbox_pending"] == 1
    assert metrics["outbox_dead_letter"] == 0
    assert metrics["outbox_published_not_acked"] == 0


def test_get_event_by_redis_message_id(outbox_repo):
    event = GraphSyncEvent.from_experiment(_experiment(), source="ingestion")
    outbox_repo.enqueue(event)
    outbox_repo.mark_published(event.event_id, "1700000000000-0")

    row = outbox_repo.get_event_by_redis_message_id("1700000000000-0")
    assert row is not None
    assert row["event_id"] == event.event_id
    assert row["status"] == STATUS_PUBLISHED

    metrics = outbox_repo.get_metrics()
    assert metrics["outbox_published_not_acked"] == 1


def test_get_sync_state_detects_lag(outbox_repo):
    event = GraphSyncEvent.from_experiment(_experiment("EXP-LAG-01"), source="ingestion")
    outbox_repo.enqueue(event)
    outbox_repo.mark_published(event.event_id, "1700000000000-0")

    state = outbox_repo.get_sync_state(["EXP-LAG-01", "EXP-MISSING"])
    assert state["published_count"] == 1
    assert state["has_lag"] is True


def test_list_backfill_candidates(outbox_repo):
    acked = GraphSyncEvent.from_experiment(_experiment("EXP-ACK-01"), source="ingestion")
    pending = GraphSyncEvent.from_experiment(_experiment("EXP-PEND-01"), source="ingestion")
    orphan = GraphSyncEvent.from_experiment(_experiment("EXP-ORPH-01"), source="ingestion")

    outbox_repo.enqueue(acked)
    outbox_repo.mark_published(acked.event_id, "1-0")
    outbox_repo.mark_acked(acked.event_id)

    outbox_repo.enqueue(pending)

    candidates = outbox_repo.list_backfill_candidates(
        ["EXP-ACK-01", "EXP-PEND-01", "EXP-ORPH-01"]
    )
    assert candidates == ["EXP-ORPH-01"]
