#!/usr/bin/env python3
"""L0–L4 E2E eval: Success Rate, E2E latency, layer snapshots."""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.repository.database import db
from backend.routers.search import synthesize_vsa_answer
from backend.evaluation.judges.llm_judge import evaluate_answer_with_llm
from backend.evaluation.judges.rule_judge import evaluate_answer
from backend.evaluation.metrics import recall_at_k
from backend.evaluation.runners.common import (
    create_run_id,
    finalize_summary,
    load_golden_questions,
    redact_secrets,
    resolve_report_dir,
)
from backend.evaluation.runners.layer_snapshots import (
    build_l0_snapshot,
    build_l1_snapshot,
    build_l2_snapshot,
    build_l3_snapshot,
    build_l4_snapshot,
    save_layer_snapshots,
)
from backend.evaluation.runners.query_parse import parse_query_with_timeout

RETRIEVAL_LIMIT = 10
TOP_K = 5


async def _run_question_pipeline(
    question: Dict[str, Any],
    *,
    use_llm: bool = True,
    use_llm_judge: bool = False,
    llm_timeout_s: float = 30.0,
) -> Dict[str, Any]:
    qid = question["id"]
    query_text = question["query"]
    expected_ids = set(question.get("expected_experiment_ids") or [])
    start = time.perf_counter()
    error: Optional[str] = None
    answer: Optional[str] = None
    vsa_latency_ms: Optional[float] = None
    neo4j_latency_ms: Optional[float] = None
    ttft_s: Optional[float] = None
    ttfa_s: Optional[float] = None

    try:
        entities = await parse_query_with_timeout(query_text, prefer_local=True)
        l0 = build_l0_snapshot(entities)

        vsa_start = time.perf_counter()
        hits = db.search(
            entities,
            limit=RETRIEVAL_LIMIT,
            geography=question.get("geography"),
            year_start=question.get("year_start"),
            year_end=question.get("year_end"),
        )
        vsa_latency_ms = round((time.perf_counter() - vsa_start) * 1000, 2)
        l1 = build_l1_snapshot(hits)
        l2 = build_l2_snapshot(hits, limit=TOP_K, geography=question.get("geography"))

        retrieved_ids = [exp.id for exp, _ in hits]
        recall5 = recall_at_k(retrieved_ids, expected_ids, TOP_K) if expected_ids else None

        counterfactuals: List[Dict[str, Any]] = []
        if hits:
            counterfactuals = db.get_counterfactuals(hits[0][0].id)
        l3 = build_l3_snapshot(counterfactuals)

        formatted = [{"experiment": exp, "similarity": score} for exp, score in hits[:TOP_K]]

        if use_llm and formatted:
            try:
                answer, ttft_s, ttfa_s = await asyncio.wait_for(
                    synthesize_vsa_answer(query_text, formatted, graph_context=None),
                    timeout=llm_timeout_s,
                )
            except asyncio.TimeoutError:
                error = "LLM Timeout"
                answer = None
            except Exception as exc:
                error = redact_secrets(str(exc))
                answer = None
        elif not formatted:
            answer = "Нет релевантных экспериментов для анализа."
        else:
            answer = "LLM synthesis skipped (dry-run mode)."

        e2e_ms = (time.perf_counter() - start) * 1000
        l4 = build_l4_snapshot(
            answer=answer,
            e2e_latency_ms=e2e_ms,
            vsa_latency_ms=vsa_latency_ms,
            neo4j_latency_ms=neo4j_latency_ms,
            ttft_s=ttft_s,
            ttfa_s=ttfa_s,
            error=error,
        )

        judge_pass: Optional[bool] = None
        judge_score: Optional[float] = None
        judge_details: Optional[str] = None
        if use_llm:
            judge = evaluate_answer(
                answer,
                question,
                retrieved_ids=retrieved_ids,
                recall_at_5=recall5,
            )
            judge_pass = judge["pass"]
            judge_score = judge["score"]
            judge_details = judge["details"]
        else:
            judge_details = "skipped: dry_run_no_llm"

        row: Dict[str, Any] = {
            "id": qid,
            "status": "error" if error == "LLM Timeout" else "ok",
            "question_category": question.get("question_category"),
            "coverage_status": question.get("coverage_status"),
            "eval_mode": question.get("eval_mode"),
            "error": error,
            "retrieved_ids": retrieved_ids,
            "recall_at_5": recall5,
            "e2e_latency_ms": round(e2e_ms, 2),
            "vsa_latency_ms": vsa_latency_ms,
            "llm_ttft_s": round(ttft_s, 4) if ttft_s is not None else None,
            "llm_ttfa_s": round(ttfa_s, 4) if ttfa_s is not None else None,
            "judge_pass": judge_pass,
            "judge_score": judge_score,
            "judge_details": judge_details,
            "layers": {"L0": l0, "L1": l1, "L2": l2, "L3": l3, "L4": l4},
        }

        if use_llm_judge and answer:
            llm_judge = await evaluate_answer_with_llm(
                query_text,
                answer,
                question.get("expected_evidence_keywords"),
                timeout_s=llm_timeout_s,
            )
            row["llm_judge_score"] = llm_judge["score"]
            row["llm_judge_pass"] = llm_judge["pass"]
            row["llm_judge_reasoning"] = redact_secrets(llm_judge.get("reasoning", ""))

        return row
    except Exception as exc:
        e2e_ms = (time.perf_counter() - start) * 1000
        return {
            "id": qid,
            "status": "error",
            "error": redact_secrets(str(exc)),
            "e2e_latency_ms": round(e2e_ms, 2),
            "judge_pass": False,
            "layers": {
                "L4": build_l4_snapshot(
                    answer=None,
                    e2e_latency_ms=e2e_ms,
                    error=redact_secrets(str(exc)),
                )
            },
        }


def run_e2e_eval(
    *,
    golden_path: Optional[Path] = None,
    run_id: Optional[str] = None,
    report_dir: Optional[Path] = None,
    use_llm: bool = True,
    use_llm_judge: bool = False,
    llm_timeout_s: float = 30.0,
) -> Dict[str, Any]:
    questions = load_golden_questions(golden_path)
    run_id = run_id or create_run_id()
    report_dir = resolve_report_dir(run_id, report_dir)

    async def _run_all() -> List[Dict[str, Any]]:
        results = []
        for question in questions:
            row = await _run_question_pipeline(
                question,
                use_llm=use_llm,
                use_llm_judge=use_llm_judge,
                llm_timeout_s=llm_timeout_s,
            )
            layers = row.pop("layers", {})
            if layers:
                row["snapshot_paths"] = save_layer_snapshots(report_dir, row["id"], layers)
            results.append(row)
        return results

    per_question = asyncio.run(_run_all())

    latencies = [q["e2e_latency_ms"] for q in per_question if q.get("e2e_latency_ms") is not None]

    aggregate: Dict[str, Any] = {}
    if use_llm:
        judged = [q for q in per_question if q.get("judge_pass") is not None]
        passed = [q for q in judged if q.get("judge_pass")]
        aggregate["success_rate"] = round(len(passed) / len(judged), 4) if judged else 0.0
        aggregate["questions_passed"] = len(passed)
        aggregate["questions_judged"] = len(judged)
    else:
        aggregate["answer_judging"] = "skipped_dry_run"
    if latencies:
        aggregate["mean_e2e_latency_ms"] = round(sum(latencies) / len(latencies), 2)

    vsa_vals = [q["vsa_latency_ms"] for q in per_question if q.get("vsa_latency_ms")]
    if vsa_vals:
        aggregate["mean_vsa_latency_ms"] = round(sum(vsa_vals) / len(vsa_vals), 2)

    ttft_vals = [q["llm_ttft_s"] for q in per_question if q.get("llm_ttft_s") is not None]
    if ttft_vals:
        aggregate["mean_ttft_s"] = round(sum(ttft_vals) / len(ttft_vals), 4)

    ttfa_vals = [q["llm_ttfa_s"] for q in per_question if q.get("llm_ttfa_s") is not None]
    if ttfa_vals:
        aggregate["mean_ttfa_s"] = round(sum(ttfa_vals) / len(ttfa_vals), 4)

    llm_judged = [q for q in per_question if q.get("llm_judge_score") is not None]
    if llm_judged:
        aggregate["mean_llm_judge_score"] = round(
            sum(q["llm_judge_score"] for q in llm_judged) / len(llm_judged),
            4,
        )
        aggregate["llm_judge_pass_rate"] = round(
            sum(1 for q in llm_judged if q.get("llm_judge_pass")) / len(llm_judged),
            4,
        )

    return finalize_summary(
        runner="run_e2e_eval",
        run_id=run_id,
        report_dir=report_dir,
        questions=questions,
        per_question=per_question,
        aggregate_metrics=aggregate,
        run_metadata_extra={"use_llm": use_llm},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="HSME E2E eval (L0–L4)")
    parser.add_argument("--golden", type=Path, default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM synthesis (dry-run)",
    )
    parser.add_argument(
        "--llm-judge",
        action="store_true",
        help="Run optional LLM-as-judge scoring",
    )
    parser.add_argument("--llm-timeout", type=float, default=30.0)
    args = parser.parse_args()
    summary = run_e2e_eval(
        golden_path=args.golden,
        run_id=args.run_id,
        use_llm=not args.no_llm,
        use_llm_judge=args.llm_judge,
        llm_timeout_s=args.llm_timeout,
    )
    print(f"E2E eval complete: {summary['artifact_paths']['report_dir']}")
    print(f"Success rate: {summary['aggregate_metrics'].get('success_rate', 0)}")
    if "mean_ttft_s" in summary["aggregate_metrics"]:
        print(f"Mean TTFT: {summary['aggregate_metrics']['mean_ttft_s']} s")
    if "mean_ttfa_s" in summary["aggregate_metrics"]:
        print(f"Mean TTFA: {summary['aggregate_metrics']['mean_ttfa_s']} s")


if __name__ == "__main__":
    main()
