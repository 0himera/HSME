"""Backfill VSA experiments into Neo4j with optional dry-run."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from backend.repository.database import db
from backend.repository.neo4j_graph import Neo4jGraphRepository, neo4j_graph

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def run_backfill(dry_run: bool = False) -> dict:
    graph = neo4j_graph
    if dry_run:
        graph = Neo4jGraphRepository(dry_run=True)

    experiments = list(db.experiments.values())
    if not dry_run and graph.is_configured:
        await graph.ensure_indexes()

    stats = {
        "total": len(experiments),
        "success": 0,
        "failed": 0,
        "planned_entities": 0,
        "planned_relations": 0,
    }

    for exp in experiments:
        plan = graph.describe_insert_plan(exp)
        stats["planned_entities"] += plan["entity_count"]
        stats["planned_relations"] += plan["semantic_relation_count"]

        if dry_run:
            logger.info(
                "DRY-RUN %s: entities=%d hyperedges=%d relations=%d evidence=%d",
                plan["experiment_id"],
                plan["entity_count"],
                plan["hyperedge_count"],
                plan["semantic_relation_count"],
                plan["evidence_count"],
            )
            stats["success"] += 1
            continue

        ok = await graph.insert_experiment_async(exp)
        if ok:
            stats["success"] += 1
        else:
            stats["failed"] += 1

    if not dry_run:
        await graph.close()

    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill HSME VSA data into Neo4j")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log planned Cypher volume without writing to Neo4j",
    )
    args = parser.parse_args(argv)

    if not args.dry_run and not neo4j_graph.is_configured:
        logger.error("Neo4j is disabled or missing credentials (USE_NEO4J / NEO4J_*).")
        return 1

    stats = asyncio.run(run_backfill(dry_run=args.dry_run))

    logger.info(
        "Backfill complete dry_run=%s total=%d success=%d failed=%d planned_entities=%d planned_relations=%d",
        args.dry_run,
        stats["total"],
        stats["success"],
        stats["failed"],
        stats["planned_entities"],
        stats["planned_relations"],
    )
    return 0 if stats["failed"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
