"""Neo4j consumer worker for Redis Streams graph sync events."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

from backend.core.graph_sync_events import GraphSyncEvent
from backend.core.config import OUTBOX_STALE_PUBLISHED_S
from backend.repository.ingestion_outbox import STATUS_DEAD_LETTER, ingestion_outbox
from backend.repository.neo4j_graph import neo4j_graph
from backend.services.graph_sync import graph_sync_service
from backend.services.redis_streams import redis_streams

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def process_message(message_id: str, fields: dict[str, str]) -> bool:
    event_id = fields.get("event_id", "")
    try:
        event = GraphSyncEvent.from_stream_fields(fields)
    except Exception as exc:
        logger.warning("Invalid stream payload message_id=%s error=%s", message_id, exc.__class__.__name__)
        if event_id:
            ingestion_outbox.mark_failed(event_id, f"bad_payload:{exc.__class__.__name__}")
        redis_streams.ack(message_id)
        return False

    if not neo4j_graph.is_configured:
        logger.error("Neo4j not configured — cannot process event_id=%s", event.event_id)
        return False

    ok = await neo4j_graph.insert_experiment_async(event.experiment)
    if ok:
        redis_streams.ack(message_id)
        ingestion_outbox.mark_acked(event.event_id)
        logger.info(
            "Neo4j consumer acked event_id=%s experiment_id=%s message_id=%s",
            event.event_id,
            event.experiment_id,
            message_id,
        )
        return True

    status = ingestion_outbox.mark_consume_failed(event.event_id, "neo4j_insert_failed")
    if status == STATUS_DEAD_LETTER:
        redis_streams.ack(message_id)
    return False


async def run_consumer_loop(
    *,
    consumer_name: str,
    batch_size: int,
    once: bool,
    idle_sleep_s: float,
) -> int:
    graph_sync_service.ensure_schema()
    if not graph_sync_service.is_async_enabled:
        logger.error("Async graph sync is disabled (USE_ASYNC_GRAPH_SYNC / USE_NEO4J).")
        return 1
    if not redis_streams.ping():
        logger.error("Redis is unavailable.")
        return 1
    if not neo4j_graph.is_configured:
        logger.error("Neo4j not configured — worker cannot start.")
        return 1
    await neo4j_graph.ensure_indexes()

    processed = 0
    while True:
        requeued_stale = ingestion_outbox.requeue_stale_published(OUTBOX_STALE_PUBLISHED_S)
        if requeued_stale:
            logger.info("Requeued %d stale published outbox event(s)", requeued_stale)

        relay_stats = graph_sync_service.publish_pending_batch(limit=batch_size)
        if relay_stats["published"]:
            logger.info("Relayed pending outbox events: %s", relay_stats)

        reclaimed = redis_streams.reclaim_pending(consumer_name, count=batch_size)
        if reclaimed:
            logger.info("Reclaimed %d pending Redis message(s)", len(reclaimed))
        for message_id, fields in reclaimed:
            if await process_message(message_id, fields):
                processed += 1

        messages = redis_streams.read_group(consumer_name, count=batch_size)
        if not messages and not reclaimed:
            if once:
                break
            await asyncio.sleep(idle_sleep_s)
            continue

        for message_id, fields in messages:
            if await process_message(message_id, fields):
                processed += 1

        if once:
            break

    logger.info("Neo4j consumer finished processed=%d", processed)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consume graph sync events and write to Neo4j.")
    parser.add_argument("--consumer-name", default=f"worker-{int(time.time())}")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--once", action="store_true", help="Process one batch then exit")
    parser.add_argument("--idle-sleep", type=float, default=1.0, help="Sleep when no messages")
    args = parser.parse_args(argv)
    return asyncio.run(
        run_consumer_loop(
            consumer_name=args.consumer_name,
            batch_size=args.batch_size,
            once=args.once,
            idle_sleep_s=args.idle_sleep,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
