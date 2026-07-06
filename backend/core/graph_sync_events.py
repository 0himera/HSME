"""Event schema for async VSA → Neo4j graph sync (Stage 3)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.core.models import Experiment

PAYLOAD_VERSION = 1
EventType = Literal["experiment_upsert"]
EventSource = Literal["api", "corpus_loader", "corpus_relabel_loader", "ingestion", "migration"]


class GraphSyncEvent(BaseModel):
    event_id: str
    event_type: EventType = "experiment_upsert"
    experiment_id: str
    occurred_at: str
    payload_version: int = PAYLOAD_VERSION
    source: EventSource = "ingestion"
    experiment: Experiment

    @classmethod
    def from_experiment(
        cls,
        experiment: Experiment,
        *,
        source: EventSource = "ingestion",
        event_id: str | None = None,
    ) -> GraphSyncEvent:
        return cls(
            event_id=event_id or str(uuid.uuid4()),
            experiment_id=experiment.id,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            source=source,
            experiment=experiment,
        )

    def to_outbox_payload(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_outbox_payload(cls, payload_json: str) -> GraphSyncEvent:
        data = json.loads(payload_json)
        version = int(data.get("payload_version", 0))
        if version != PAYLOAD_VERSION:
            raise ValueError(f"Unsupported payload_version={version}")
        return cls.model_validate(data)

    def to_stream_fields(self) -> dict[str, str]:
        """Flat string fields for Redis Streams XADD."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "experiment_id": self.experiment_id,
            "payload_version": str(self.payload_version),
            "source": self.source,
            "occurred_at": self.occurred_at,
            "payload": self.experiment.model_dump_json(),
        }

    @classmethod
    def from_stream_fields(cls, fields: dict[str, Any]) -> GraphSyncEvent:
        payload = fields.get("payload")
        if payload:
            experiment = Experiment.model_validate_json(payload)
        else:
            experiment = Experiment.model_validate_json(fields["experiment"])
        return cls(
            event_id=str(fields["event_id"]),
            event_type=fields.get("event_type", "experiment_upsert"),
            experiment_id=str(fields["experiment_id"]),
            occurred_at=str(fields.get("occurred_at", "")),
            payload_version=int(fields.get("payload_version", PAYLOAD_VERSION)),
            source=fields.get("source", "ingestion"),
            experiment=experiment,
        )
