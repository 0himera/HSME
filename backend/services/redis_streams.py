"""Redis Streams transport for graph sync events."""

from __future__ import annotations

import logging
from typing import Any

from backend.core.config import (
    BROKER_DRY_RUN,
    REDIS_CONSUMER_BLOCK_MS,
    REDIS_CONSUMER_GROUP,
    REDIS_PENDING_MIN_IDLE_MS,
    REDIS_PUBLISH_TIMEOUT,
    REDIS_STREAM_KEY,
    REDIS_URL,
    USE_ASYNC_GRAPH_SYNC,
)

logger = logging.getLogger(__name__)


class RedisStreamsClient:
    """Thin wrapper around Redis Streams XADD / XREADGROUP / XACK."""

    def __init__(
        self,
        *,
        redis_url: str = REDIS_URL,
        stream_key: str = REDIS_STREAM_KEY,
        consumer_group: str = REDIS_CONSUMER_GROUP,
        enabled: bool = USE_ASYNC_GRAPH_SYNC,
        dry_run: bool = BROKER_DRY_RUN,
    ) -> None:
        self.redis_url = redis_url
        self.stream_key = stream_key
        self.consumer_group = consumer_group
        self.enabled = enabled
        self.dry_run = dry_run
        self._client: Any = None

    @property
    def is_configured(self) -> bool:
        return bool(self.enabled and self.redis_url)

    def _get_client(self):
        if self._client is None:
            import redis

            self._client = redis.Redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=REDIS_PUBLISH_TIMEOUT,
                socket_timeout=REDIS_PUBLISH_TIMEOUT,
            )
        return self._client

    def ping(self) -> bool:
        if not self.is_configured:
            return False
        if self.dry_run:
            return True
        try:
            return bool(self._get_client().ping())
        except Exception as exc:
            logger.warning("Redis ping failed: %s", exc.__class__.__name__)
            return False

    def ensure_consumer_group(self) -> None:
        if not self.is_configured or self.dry_run:
            return
        client = self._get_client()
        try:
            client.xgroup_create(self.stream_key, self.consumer_group, id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def publish(self, fields: dict[str, str]) -> str:
        if not self.is_configured:
            raise RuntimeError("Redis Streams client is not configured")
        if self.dry_run:
            logger.info("Redis dry-run XADD stream=%s event_id=%s", self.stream_key, fields.get("event_id"))
            return f"dry-run-{fields.get('event_id', 'unknown')}"
        message_id = self._get_client().xadd(self.stream_key, fields)
        return str(message_id)

    def read_group(
        self,
        consumer_name: str,
        *,
        count: int = 10,
        block_ms: int = REDIS_CONSUMER_BLOCK_MS,
    ) -> list[tuple[str, dict[str, str]]]:
        if not self.is_configured:
            return []
        if self.dry_run:
            return []
        self.ensure_consumer_group()
        client = self._get_client()
        response = client.xreadgroup(
            self.consumer_group,
            consumer_name,
            {self.stream_key: ">"},
            count=count,
            block=block_ms,
        )
        return self._parse_xreadgroup_response(response)

    def reclaim_pending(
        self,
        consumer_name: str,
        *,
        count: int = 10,
        min_idle_ms: int = REDIS_PENDING_MIN_IDLE_MS,
    ) -> list[tuple[str, dict[str, str]]]:
        """Reclaim stale pending messages from other/dead consumers."""
        if not self.is_configured or self.dry_run:
            return []
        self.ensure_consumer_group()
        client = self._get_client()
        messages: list[tuple[str, dict[str, str]]] = []

        if hasattr(client, "xautoclaim"):
            start_id = "0-0"
            while len(messages) < count:
                result = client.xautoclaim(
                    self.stream_key,
                    self.consumer_group,
                    consumer_name,
                    min_idle_ms,
                    start_id,
                    count=count - len(messages),
                )
                if len(result) == 3:
                    start_id, entries, _deleted = result
                else:
                    start_id, entries = result[0], result[1]
                if not entries:
                    break
                for message_id, fields in entries:
                    messages.append((str(message_id), dict(fields)))
                if start_id in ("0-0", "0"):
                    break
            return messages

        pending = client.xpending_range(
            self.stream_key,
            self.consumer_group,
            min="-",
            max="+",
            count=count,
        )
        if not pending:
            return []
        message_ids = [item["message_id"] for item in pending]
        claimed = client.xclaim(
            self.stream_key,
            self.consumer_group,
            consumer_name,
            min_idle_ms,
            message_ids,
        )
        for message_id, fields in claimed or []:
            messages.append((str(message_id), dict(fields)))
        return messages

    @staticmethod
    def _parse_xreadgroup_response(response) -> list[tuple[str, dict[str, str]]]:
        messages: list[tuple[str, dict[str, str]]] = []
        for _stream, entries in response or []:
            for message_id, fields in entries:
                messages.append((str(message_id), dict(fields)))
        return messages

    def ack(self, message_id: str) -> None:
        if not self.is_configured or self.dry_run:
            return
        self._get_client().xack(self.stream_key, self.consumer_group, message_id)


redis_streams = RedisStreamsClient()
