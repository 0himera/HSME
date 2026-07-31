#!/usr/bin/env python3
"""L1–L2 retrieval eval: Precision, Recall, P@K, R@K, MRR."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.repository.database import db
from backend.evaluation.metrics import (
    aggregate_metric,
    mean_reciprocal_rank,
    precision,
    precision_at_k,
    recall,
    recall_at_k,
)
from backend.evaluation.runners.common import (
    create_run_id,
    finalize_summary,
    load_golden_questions,
    resolve_report_dir,
)
from backend.evaluation.runners.query_parse import parse_query_sync

DEFAULT_K_VALUES = [3, 5, 10]


def run_retrieval_eval(
    *,
    golden_path: Optional[Path] = None,
    run_id: Optional[str] = None,
    report_dir: Optional[Path] = None,
    k_values: Optional[List[int]] = None,
    limit: int = 10,
    prefer_local: bool = False,
) -> Dict[str, Any]:
    ks = k_values or DEFAULT_K_VALUES
    questions = load_golden_questions(golden_path)
    run_id = run_id or create_run_id()
    report_dir = resolve_report_dir(run_id, report_dir)

    per_question: List[Dict[str, Any]] = []
    retrieval_runs = 0

    for question in questions:
        qid = question["id"]
        expected_ids = question.get("expected_experiment_ids") or []
        eval_mode = question.get("eval_mode", "full")

        if not expected_ids or eval_mode == "e2e_only":
            per_question.append(
                {
                    "id": qid,
                    "status": "skipped",
                    "retrieval_skipped": True,
                    "skip_reason": "no expected_experiment_ids or e2e_only",
                    "coverage_status": question.get("coverage_status"),
                }
            )
            continue

        relevant = set(expected_ids)
        start = time.perf_counter()
        try:
            entities = parse_query_sync(question["query"], prefer_local=prefer_local)
            hits = db.search(
                entities,
                limit=limit,
                geography=question.get("geography"),
                year_start=question.get("year_start"),
                year_end=question.get("year_end"),
            )
            retrieved_ids = [exp.id for exp, _ in hits]
            latency_ms = (time.perf_counter() - start) * 1000

            metrics = {
                "precision": precision(retrieved_ids, relevant),
                "recall": recall(retrieved_ids, relevant),
                "mrr": mean_reciprocal_rank(retrieved_ids, relevant),
                "retrieval_latency_ms": round(latency_ms, 2),
            }
            for k in ks:
                metrics[f"precision_at_{k}"] = precision_at_k(retrieved_ids, relevant, k)
                metrics[f"recall_at_{k}"] = recall_at_k(retrieved_ids, relevant, k)

            per_question.append(
                {
                    "id": qid,
                    "status": "ok",
                    "retrieval_skipped": False,
                    "coverage_status": question.get("coverage_status"),
                    "parsed_entities": [{"type": e.type, "value": e.value} for e in entities],
                    "retrieved_ids": retrieved_ids,
                    "expected_ids": list(relevant),
                    "metrics": metrics,
                }
            )
            retrieval_runs += 1
        except Exception as exc:
            per_question.append(
                {
                    "id": qid,
                    "status": "error",
                    "error": str(exc),
                    "retrieval_skipped": False,
                }
            )

    ok_rows = [q for q in per_question if q.get("status") == "ok"]
    aggregate: Dict[str, Any] = {"retrieval_evaluated": retrieval_runs}
    if ok_rows:
        for key in ("precision", "recall", "mrr"):
            aggregate[key] = round(
                aggregate_metric(q["metrics"][key] for q in ok_rows),
                4,
            )
        for k in ks:
            aggregate[f"precision_at_{k}"] = round(
                aggregate_metric(q["metrics"][f"precision_at_{k}"] for q in ok_rows),
                4,
            )
            aggregate[f"recall_at_{k}"] = round(
                aggregate_metric(q["metrics"][f"recall_at_{k}"] for q in ok_rows),
                4,
            )
        aggregate["mean_retrieval_latency_ms"] = round(
            aggregate_metric(q["metrics"]["retrieval_latency_ms"] for q in ok_rows),
            2,
        )

    return finalize_summary(
        runner="run_retrieval_eval",
        run_id=run_id,
        report_dir=report_dir,
        questions=questions,
        per_question=per_question,
        aggregate_metrics=aggregate,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="HSME retrieval eval (L1–L2)")
    parser.add_argument(
        "--golden",
        type=Path,
        default=None,
        help="Path to questions.jsonl",
    )
    parser.add_argument("--run-id", default=None, help="Override run id")
    parser.add_argument(
        "--prefer-local",
        action="store_true",
        help="Force regex-only local query parsing instead of LLM",
    )
    args = parser.parse_args()
    summary = run_retrieval_eval(
        golden_path=args.golden,
        run_id=args.run_id,
        prefer_local=args.prefer_local,
    )
    print(f"Retrieval eval complete: {summary['artifact_paths']['report_dir']}")


if __name__ == "__main__":
    main()
