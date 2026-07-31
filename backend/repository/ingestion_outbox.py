"""Durable SQLite outbox for async Neo4j graph sync events."""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from backend.core.config import OUTBOX_DB_PATH, OUTBOX_MAX_ATTEMPTS
from backend.core.graph_sync_events import GraphSyncEvent

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_PUBLISHED = "published"
STATUS_ACKED = "acked"
STATUS_DEAD_LETTER = "dead_letter"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class IngestionOutboxRepository:
    """Transactional outbox backed by SQLite."""

    def __init__(self, db_path: str = OUTBOX_DB_PATH) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        import os

        dirpath = os.path.dirname(self.db_path)
        if dirpath:
            os.makedirs(dirpath, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def ensure_schema(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS graph_sync_outbox (
                        event_id TEXT PRIMARY KEY,
                        event_type TEXT NOT NULL,
                        experiment_id TEXT NOT NULL,
                        payload_version INTEGER NOT NULL,
                        source TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        attempts INTEGER NOT NULL DEFAULT 0,
                        redis_message_id TEXT,
                        error_message TEXT,
                        occurred_at TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_outbox_status ON graph_sync_outbox(status)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_outbox_experiment ON graph_sync_outbox(experiment_id)"
                )

    def enqueue(self, event: GraphSyncEvent) -> str:
        """Insert event; idempotent on event_id."""
        now = _utc_now_iso()
        with self._lock:
            with self._connect() as conn:
                existing = conn.execute(
                    "SELECT event_id FROM graph_sync_outbox WHERE event_id = ?",
                    (event.event_id,),
                ).fetchone()
                if existing:
                    return event.event_id
                conn.execute(
                    """
                    INSERT INTO graph_sync_outbox (
                        event_id, event_type, experiment_id, payload_version, source,
                        payload_json, status, attempts, occurred_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.event_type,
                        event.experiment_id,
                        event.payload_version,
                        event.source,
                        event.to_outbox_payload(),
                        STATUS_PENDING,
                        event.occurred_at,
                        now,
                        now,
                    ),
                )
        return event.event_id

    def list_pending(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM graph_sync_outbox
                    WHERE status = ?
                    ORDER BY created_at ASC
                    LIMIT ?
                    """,
                    (STATUS_PENDING, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM graph_sync_outbox WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
        return dict(row) if row else None

    def get_event_by_redis_message_id(self, redis_message_id: str) -> dict[str, Any] | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM graph_sync_outbox WHERE redis_message_id = ?",
                    (redis_message_id,),
                ).fetchone()
        return dict(row) if row else None

    def mark_published(self, event_id: str, redis_message_id: str) -> None:
        now = _utc_now_iso()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE graph_sync_outbox
                    SET status = ?, redis_message_id = ?, updated_at = ?, error_message = NULL
                    WHERE event_id = ?
                    """,
                    (STATUS_PUBLISHED, redis_message_id, now, event_id),
                )

    def mark_acked(self, event_id: str) -> None:
        now = _utc_now_iso()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE graph_sync_outbox
                    SET status = ?, updated_at = ?, error_message = NULL
                    WHERE event_id = ?
                    """,
                    (STATUS_ACKED, now, event_id),
                )

    def mark_failed(self, event_id: str, error_message: str) -> None:
        """Relay/publish failure — revert to pending for re-publish (or dead-letter)."""
        now = _utc_now_iso()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT attempts FROM graph_sync_outbox WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                if not row:
                    return
                attempts = int(row["attempts"]) + 1
                status = STATUS_DEAD_LETTER if attempts >= OUTBOX_MAX_ATTEMPTS else STATUS_PENDING
                conn.execute(
                    """
                    UPDATE graph_sync_outbox
                    SET attempts = ?, status = ?, error_message = ?, updated_at = ?
                    WHERE event_id = ?
                    """,
                    (attempts, status, error_message[:500], now, event_id),
                )

    def mark_consume_failed(self, event_id: str, error_message: str) -> str:
        """Consumer failure — keep published for PEL reclaim; dead-letter after max attempts."""
        now = _utc_now_iso()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT attempts FROM graph_sync_outbox WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                if not row:
                    return STATUS_PUBLISHED
                attempts = int(row["attempts"]) + 1
                status = STATUS_DEAD_LETTER if attempts >= OUTBOX_MAX_ATTEMPTS else STATUS_PUBLISHED
                conn.execute(
                    """
                    UPDATE graph_sync_outbox
                    SET attempts = ?, status = ?, error_message = ?, updated_at = ?
                    WHERE event_id = ?
                    """,
                    (attempts, status, error_message[:500], now, event_id),
                )
                return status

    def list_backfill_candidates(self, experiment_ids: list[str]) -> list[str]:
        """Experiment IDs with no pending/published/acked outbox row (orphans for backfill)."""
        if not experiment_ids:
            return []
        placeholders = ",".join("?" * len(experiment_ids))
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT experiment_id FROM graph_sync_outbox
                    WHERE experiment_id IN ({placeholders})
                    AND status IN (?, ?, ?)
                    """,
                    (*experiment_ids, STATUS_PENDING, STATUS_PUBLISHED, STATUS_ACKED),
                ).fetchall()
        active = {row["experiment_id"] for row in rows}
        return [exp_id for exp_id in experiment_ids if exp_id not in active]

    def get_sync_state(self, experiment_ids: list[str]) -> dict[str, Any]:
        """Lag snapshot for experiment IDs still pending or published in outbox."""
        if not experiment_ids:
            return {
                "pending_count": 0,
                "published_count": 0,
                "has_lag": False,
            }
        placeholders = ",".join("?" * len(experiment_ids))
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT status, COUNT(*) AS cnt
                    FROM graph_sync_outbox
                    WHERE experiment_id IN ({placeholders})
                    AND status IN (?, ?)
                    GROUP BY status
                    """,
                    (*experiment_ids, STATUS_PENDING, STATUS_PUBLISHED),
                ).fetchall()
        by_status = {row["status"]: int(row["cnt"]) for row in rows}
        pending = by_status.get(STATUS_PENDING, 0)
        published = by_status.get(STATUS_PUBLISHED, 0)
        return {
            "pending_count": pending,
            "published_count": published,
            "has_lag": (pending + published) > 0,
        }

    def requeue_stale_published(self, older_than_s: int = 300) -> int:
        """Reset long-unacked published rows to pending for relay replay."""
        from datetime import timedelta

        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_s)).isoformat()
        now = _utc_now_iso()
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    UPDATE graph_sync_outbox
                    SET status = ?, redis_message_id = NULL, updated_at = ?
                    WHERE status = ? AND updated_at < ?
                    """,
                    (STATUS_PENDING, now, STATUS_PUBLISHED, cutoff),
                )
                return cursor.rowcount

    def requeue_dead_letters(self) -> int:
        """Reset dead-letter rows to pending for manual replay."""
        now = _utc_now_iso()
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    UPDATE graph_sync_outbox
                    SET status = ?, attempts = 0, error_message = NULL, updated_at = ?
                    WHERE status = ?
                    """,
                    (STATUS_PENDING, now, STATUS_DEAD_LETTER),
                )
                return cursor.rowcount

    def get_metrics(self) -> dict[str, Any]:
        with self._lock:
            with self._connect() as conn:
                counts = conn.execute(
                    """
                    SELECT status, COUNT(*) AS cnt
                    FROM graph_sync_outbox
                    GROUP BY status
                    """
                ).fetchall()
                oldest = conn.execute(
                    """
                    SELECT MIN(created_at) AS oldest
                    FROM graph_sync_outbox
                    WHERE status IN (?, ?)
                    """,
                    (STATUS_PENDING, STATUS_PUBLISHED),
                ).fetchone()
        by_status = {row["status"]: int(row["cnt"]) for row in counts}
        pending = by_status.get(STATUS_PENDING, 0)
        published = by_status.get(STATUS_PUBLISHED, 0)
        dead_letter = by_status.get(STATUS_DEAD_LETTER, 0)
        acked = by_status.get(STATUS_ACKED, 0)
        oldest_pending_age_s = None
        if oldest and oldest["oldest"]:
            try:
                oldest_dt = datetime.fromisoformat(oldest["oldest"])
                oldest_pending_age_s = (
                    datetime.now(timezone.utc) - oldest_dt.replace(tzinfo=timezone.utc)
                ).total_seconds()
            except ValueError:
                oldest_pending_age_s = None
        return {
            "outbox_pending": pending,
            "outbox_published_not_acked": published,
            "outbox_dead_letter": dead_letter,
            "outbox_acked": acked,
            "oldest_pending_age_s": oldest_pending_age_s,
        }


ingestion_outbox = IngestionOutboxRepository()
