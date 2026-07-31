"""Orchestration for VSA-first async Neo4j graph sync."""

from __future__ import annotations

import logging
from typing import Any

from backend.core.config import (
    ASYNC_GRAPH_SYNC_REQUIRED,
    OUTBOX_PUBLISH_BATCH_SIZE,
    USE_ASYNC_GRAPH_SYNC,
    USE_NEO4J,
)
from backend.core.graph_sync_events import EventSource, GraphSyncEvent
from backend.core.models import Experiment
from backend.repository.ingestion_outbox import ingestion_outbox
from backend.repository.neo4j_graph import neo4j_graph
from backend.services.redis_streams import redis_streams

logger = logging.getLogger(__name__)


class GraphSyncService:
    """Enqueue experiment upserts and relay them to Redis Streams."""

    def __init__(self) -> None:
        self._schema_ready = False

    @property
    def is_async_enabled(self) -> bool:
        return bool(USE_NEO4J and USE_ASYNC_GRAPH_SYNC and neo4j_graph.is_configured)

    def ensure_schema(self) -> None:
        if not self._schema_ready:
            ingestion_outbox.ensure_schema()
            self._schema_ready = True

    def status_snapshot(self) -> dict[str, Any]:
        self.ensure_schema()
        metrics = ingestion_outbox.get_metrics()
        redis_ok = redis_streams.ping() if self.is_async_enabled else None
        return {
            "async_graph_sync_enabled": self.is_async_enabled,
            "async_graph_sync_required": ASYNC_GRAPH_SYNC_REQUIRED,
            "redis_available": redis_ok,
            **metrics,
        }

    def _check_broker_required(self) -> None:
        if self.is_async_enabled and ASYNC_GRAPH_SYNC_REQUIRED and not redis_streams.ping():
            raise RuntimeError("Async graph sync required but Redis is unavailable")

    async def enqueue_experiment_upsert(
        self,
        experiment: Experiment,
        *,
        source: EventSource = "ingestion",
    ) -> str:
        """Persist event to outbox and best-effort relay to Redis."""
        self.ensure_schema()
        self._check_broker_required()
        event = GraphSyncEvent.from_experiment(experiment, source=source)
        event_id = ingestion_outbox.enqueue(event)
        logger.info(
            "Graph sync enqueued event_id=%s experiment_id=%s source=%s",
            event_id,
            experiment.id,
            source,
        )
        try:
            stats = self.publish_pending_batch(limit=1, event_ids={event_id})
        except Exception as exc:
            logger.warning(
                "Graph sync relay deferred event_id=%s error=%s",
                event_id,
                exc.__class__.__name__,
            )
            if ASYNC_GRAPH_SYNC_REQUIRED:
                raise
            return event_id
        if ASYNC_GRAPH_SYNC_REQUIRED and stats.get("failed", 0) > 0:
            raise RuntimeError(f"Graph sync relay failed for event_id={event_id}")
        return event_id

    def publish_pending_batch(
        self,
        *,
        limit: int = OUTBOX_PUBLISH_BATCH_SIZE,
        event_ids: set[str] | None = None,
    ) -> dict[str, int]:
        """Relay pending outbox rows to Redis Streams."""
        self.ensure_schema()
        if not self.is_async_enabled:
            return {"published": 0, "failed": 0}
        if not redis_streams.is_configured:
            if ASYNC_GRAPH_SYNC_REQUIRED:
                raise RuntimeError("Redis is not configured for async graph sync")
            return {"published": 0, "failed": 0}

        pending = ingestion_outbox.list_pending(limit=limit)
        if event_ids is not None:
            pending = [row for row in pending if row["event_id"] in event_ids]

        published = 0
        failed = 0
        for row in pending:
            event_id = row["event_id"]
            try:
                event = GraphSyncEvent.from_outbox_payload(row["payload_json"])
                message_id = redis_streams.publish(event.to_stream_fields())
                ingestion_outbox.mark_published(event_id, message_id)
                published += 1
            except Exception as exc:
                failed += 1
                ingestion_outbox.mark_failed(event_id, exc.__class__.__name__)
                logger.warning(
                    "Graph sync publish failed event_id=%s error=%s",
                    event_id,
                    exc.__class__.__name__,
                )
        return {"published": published, "failed": failed}


graph_sync_service = GraphSyncService()
