"""CLI to relay pending outbox events and recover dead-letter rows."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from backend.repository.ingestion_outbox import ingestion_outbox
from backend.services.graph_sync import graph_sync_service

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay graph sync outbox events to Redis Streams.")
    parser.add_argument(
        "--requeue-dead-letters",
        action="store_true",
        help="Reset dead-letter rows to pending before relay",
    )
    parser.add_argument(
        "--requeue-stale-published",
        type=int,
        metavar="SECONDS",
        help="Reset published-but-unacked rows older than SECONDS to pending before relay",
    )
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true", help="Print metrics only, no publish")
    args = parser.parse_args(argv)

    graph_sync_service.ensure_schema()
    before = ingestion_outbox.get_metrics()

    requeued = 0
    requeued_stale = 0
    if args.requeue_dead_letters:
        requeued = ingestion_outbox.requeue_dead_letters()
        logger.info("Requeued dead-letter events: %d", requeued)
    if args.requeue_stale_published is not None:
        requeued_stale = ingestion_outbox.requeue_stale_published(args.requeue_stale_published)
        logger.info("Requeued stale published events: %d", requeued_stale)

    publish_stats = {"published": 0, "failed": 0}
    if not args.dry_run:
        publish_stats = graph_sync_service.publish_pending_batch(limit=args.batch_size)

    after = ingestion_outbox.get_metrics()
    report = {
        "requeued_dead_letters": requeued,
        "requeued_stale_published": requeued_stale,
        "publish_stats": publish_stats,
        "metrics_before": before,
        "metrics_after": after,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if publish_stats.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
