#!/usr/bin/env python3
"""L0–L4 E2E eval: Success Rate, E2E latency, layer snapshots.

By default this runner exercises the **logical pipeline** (direct db/search + synthesize calls).
Use ``--via-api`` for HTTP contract smoke tests against ``POST /api/search`` via ASGI transport.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from httpx import ASGITransport

from backend.app import app
from backend.core.config import NEO4J_INTERACTIVE_TIMEOUT
from backend.repository.database import db
from backend.repository.neo4j_graph import neo4j_graph
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
    build_l1_pre_rerank_snapshot,
    build_l1_snapshot,
    build_l2_snapshot,
    build_l3_snapshot,
    build_l4_snapshot,
    save_layer_snapshots,
)
from backend.evaluation.runners.query_parse import parse_query_with_timeout
from backend.services.rerank import RankedHit, hybrid_rerank
from backend.services.retrieval_gate import (
    NO_EVIDENCE_ANSWER,
    evaluate_retrieval_gate,
    sanitize_query_entities,
)

RETRIEVAL_LIMIT = 10
TOP_K = 5
logger = logging.getLogger(__name__)
API_HEADERS = {
    "X-User-Name": "eval-runner",
    "X-User-Role": "Administrator",
}


def _empty_layer_snapshots(*, via_api: bool = False) -> Dict[str, Dict[str, Any]]:
    marker = {"via_api": True} if via_api else {}
    return {
        "L0": {"entities": [], **marker},
        "L1_pre_rerank": {"stage": "pre_rerank", "hits": [], **marker},
        "L1": {"stage": "post_rerank", "hits": [], **marker},
        "L2": {"limit": TOP_K, "top_k": [], **marker},
        "L3": {"counterfactuals": [], **marker},
    }


def _api_hit_dict(item: Dict[str, Any]) -> Dict[str, Any]:
    exp = item.get("experiment") or {}
    vsa = float(item.get("vsa_score", item.get("similarity", 0.0)) or 0.0)
    hybrid = item.get("hybrid_score")
    row: Dict[str, Any] = {
        "experiment_id": exp.get("id", ""),
        "name": exp.get("name", ""),
        "vsa_score": round(vsa, 4),
        "similarity": round(vsa, 4),
    }
    if hybrid is not None:
        row["hybrid_score"] = round(float(hybrid), 4)
    if item.get("score_breakdown"):
        row["score_breakdown"] = item["score_breakdown"]
    return row


async def _fetch_graph_context(
    exp_ids: List[str],
    *,
    timeout_s: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Neo4j graph context with interactive timeout; soft-fail to error context / None."""
    if not neo4j_graph.is_configured or not exp_ids:
        return None
    budget = timeout_s if timeout_s is not None else (NEO4J_INTERACTIVE_TIMEOUT + 0.5)
    try:
        ctx = await asyncio.wait_for(
            neo4j_graph.expand_graph_context(exp_ids),
            timeout=budget,
        )
        return ctx
    except asyncio.TimeoutError:
        logger.warning("Neo4j expand_graph_context timed out after %.1fs", budget)
        return {
            "paths": [],
            "experts": [],
            "publications": [],
            "contradictions": [],
            "neo4j_latency_ms": budget * 1000,
            "neo4j_error": True,
        }
    except Exception as exc:
        logger.warning(
            "Neo4j expand_graph_context failed: %s",
            exc.__class__.__name__,
        )
        return {
            "paths": [],
            "experts": [],
            "publications": [],
            "contradictions": [],
            "neo4j_latency_ms": 0.0,
            "neo4j_error": True,
        }


async def _run_question_via_api(
    question: Dict[str, Any],
    client: httpx.AsyncClient,
    *,
    use_llm: bool = True,
    use_llm_judge: bool = False,
    llm_timeout_s: float = 30.0,
) -> Dict[str, Any]:
    """Smoke-test E2E through POST /api/search (HTTP contract path)."""
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
    retrieved_ids: List[str] = []
    recall5: Optional[float] = None

    layers = _empty_layer_snapshots(via_api=True)

    payload: Dict[str, Any] = {
        "query": query_text,
        "paged": True,
        "limit": TOP_K,
    }
    if question.get("geography"):
        payload["geography"] = question["geography"]
    if question.get("year_start") is not None:
        payload["year_start"] = question["year_start"]
    if question.get("year_end") is not None:
        payload["year_end"] = question["year_end"]

    try:
        response = await client.post(
            "/api/search",
            json=payload,
            headers=API_HEADERS,
            timeout=llm_timeout_s + 10.0,
        )
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            results = data.get("results") or []
            retrieved_ids = [
                item["experiment"]["id"]
                for item in results
                if isinstance(item, dict) and item.get("experiment")
            ]
            vsa_latency_ms = data.get("vsa_latency_ms")
            neo4j_latency_ms = data.get("neo4j_latency_ms")
            ttft_s = data.get("llm_ttft_s")
            ttfa_s = data.get("llm_ttfa_s")
            answer = data.get("rag_explanation")
            parsed_entities = data.get("parsed_entities") or []
            layers["L0"] = {
                "entities": parsed_entities,
                "parse_source": data.get("parse_source"),
                "via_api": True,
                "retrieval_empty_reason": data.get("retrieval_empty_reason"),
                "gate_stage": data.get("gate_stage"),
                "gate_reason": data.get("retrieval_empty_reason"),
                "gate_signals": data.get("gate_signals"),
            }
            pre_ids = data.get("pre_rerank_top5") or []
            layers["L1_pre_rerank"] = {
                "stage": "pre_rerank",
                "hits": [{"experiment_id": eid} for eid in pre_ids],
                "via_api": True,
            }
            layers["L1"] = {
                "stage": "post_rerank",
                "hits": [
                    _api_hit_dict(item)
                    for item in results
                    if isinstance(item, dict) and item.get("experiment")
                ],
                "via_api": True,
                "post_rerank_top5": data.get("post_rerank_top5") or retrieved_ids[:5],
            }
            layers["L2"] = {
                "limit": TOP_K,
                "geography_filter": question.get("geography"),
                "top_k": layers["L1"]["hits"][:TOP_K],
                "via_api": True,
            }
        elif isinstance(data, list):
            retrieved_ids = [
                item["experiment"]["id"]
                for item in data
                if isinstance(item, dict) and item.get("experiment")
            ]
            layers["L0"] = {"entities": [], "via_api": True, "parse_source": "unavailable_non_paged"}
            layers["L1"] = {
                "stage": "post_rerank",
                "hits": [
                    _api_hit_dict(item)
                    for item in data
                    if isinstance(item, dict) and item.get("experiment")
                ],
                "via_api": True,
            }

        if expected_ids:
            recall5 = recall_at_k(retrieved_ids, expected_ids, TOP_K)

        if not use_llm:
            answer = answer or "LLM synthesis skipped (dry-run mode)."
            judge_details = "skipped: dry_run_no_llm"
            judge_pass = None
            judge_score = None
        else:
            judge = evaluate_answer(
                answer,
                question,
                retrieved_ids=retrieved_ids,
                recall_at_5=recall5,
            )
            judge_pass = judge["pass"]
            judge_score = judge["score"]
            judge_details = judge["details"]

        e2e_ms = (time.perf_counter() - start) * 1000
        layers["L4"] = build_l4_snapshot(
            answer=answer,
            e2e_latency_ms=e2e_ms,
            vsa_latency_ms=vsa_latency_ms,
            neo4j_latency_ms=neo4j_latency_ms,
            ttft_s=ttft_s,
            ttfa_s=ttfa_s,
            error=error,
        )

        row: Dict[str, Any] = {
            "id": qid,
            "status": "ok",
            "question_category": question.get("question_category"),
            "coverage_status": question.get("coverage_status"),
            "eval_mode": question.get("eval_mode"),
            "error": error,
            "retrieved_ids": retrieved_ids,
            "recall_at_5": recall5,
            "e2e_latency_ms": round(e2e_ms, 2),
            "vsa_latency_ms": vsa_latency_ms,
            "neo4j_latency_ms": neo4j_latency_ms,
            "llm_ttft_s": round(ttft_s, 4) if ttft_s is not None else None,
            "llm_ttfa_s": round(ttfa_s, 4) if ttfa_s is not None else None,
            "judge_pass": judge_pass,
            "judge_score": judge_score,
            "judge_details": judge_details,
            "via_api": True,
            "layers": layers,
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
    except httpx.HTTPStatusError as exc:
        error = f"HTTP {exc.response.status_code}: {redact_secrets(exc.response.text[:200])}"
    except httpx.TimeoutException:
        error = "HTTP Timeout"
    except Exception as exc:
        error = redact_secrets(str(exc))

    e2e_ms = (time.perf_counter() - start) * 1000
    layers["L4"] = build_l4_snapshot(
        answer=None,
        e2e_latency_ms=e2e_ms,
        error=error,
    )
    return {
        "id": qid,
        "status": "error",
        "error": error,
        "e2e_latency_ms": round(e2e_ms, 2),
        "judge_pass": False,
        "via_api": True,
        "layers": layers,
    }


async def _run_question_pipeline(
    question: Dict[str, Any],
    *,
    use_llm: bool = True,
    use_llm_judge: bool = False,
    llm_timeout_s: float = 30.0,
    prefer_local: bool = False,
    skip_neo4j: bool = False,
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
        entities = await parse_query_with_timeout(query_text, prefer_local=prefer_local)
        entities = sanitize_query_entities(entities)
        parse_source = "prefer_local" if prefer_local else "llm_or_local"

        vsa_start = time.perf_counter()
        vsa_hits = db.search(
            entities,
            limit=RETRIEVAL_LIMIT,
            geography=question.get("geography"),
            year_start=question.get("year_start"),
            year_end=question.get("year_end"),
        ) if entities else []
        vsa_latency_ms = round((time.perf_counter() - vsa_start) * 1000, 2)

        l1_pre = build_l1_pre_rerank_snapshot(vsa_hits)
        gate = evaluate_retrieval_gate(entities, vsa_hits)
        empty_gate = gate.should_empty
        l0 = build_l0_snapshot(
            entities,
            parse_source=parse_source,
            gate_stage=gate.stage or None,
            gate_reason=gate.reason or None,
            gate_signals=gate.signals,
            retrieval_empty_reason=gate.reason if empty_gate else None,
        )

        graph_context = None
        # Skip Neo4j when dry-run (--no-llm) or explicit --skip-neo4j: context unused.
        fetch_neo4j = (not skip_neo4j) and use_llm and bool(vsa_hits) and not empty_gate
        if fetch_neo4j:
            pool_ids = [exp.id for exp, _ in vsa_hits]
            graph_context = await _fetch_graph_context(pool_ids)
            if graph_context:
                neo4j_latency_ms = graph_context.get("neo4j_latency_ms", 0.0)

        ranked: List[RankedHit] = []
        if not empty_gate:
            ranked = hybrid_rerank(entities, vsa_hits, graph_context=graph_context)
        l1 = build_l1_snapshot(ranked)
        l2 = build_l2_snapshot(ranked, limit=TOP_K, geography=question.get("geography"))

        retrieved_ids = [h.experiment.id for h in ranked]
        recall5 = recall_at_k(retrieved_ids, expected_ids, TOP_K) if expected_ids else None

        counterfactuals: List[Dict[str, Any]] = []
        if ranked:
            counterfactuals = db.get_counterfactuals(ranked[0].experiment.id)
        l3 = build_l3_snapshot(counterfactuals)

        formatted = [h.as_result_dict() for h in ranked[:TOP_K]]

        if use_llm and formatted:
            try:
                answer, ttft_s, ttfa_s = await asyncio.wait_for(
                    synthesize_vsa_answer(query_text, formatted, graph_context=graph_context),
                    timeout=llm_timeout_s,
                )
            except asyncio.TimeoutError:
                error = "LLM Timeout"
                answer = None
            except Exception as exc:
                error = redact_secrets(str(exc))
                answer = None
        elif not formatted:
            answer = NO_EVIDENCE_ANSWER
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
            "neo4j_latency_ms": neo4j_latency_ms,
            "llm_ttft_s": round(ttft_s, 4) if ttft_s is not None else None,
            "llm_ttfa_s": round(ttfa_s, 4) if ttfa_s is not None else None,
            "judge_pass": judge_pass,
            "judge_score": judge_score,
            "judge_details": judge_details,
            "empty_gate": empty_gate,
            "retrieval_empty_reason": gate.reason if empty_gate else None,
            "gate_stage": gate.stage or None,
            "gate_signals": gate.signals,
            "layers": {
                "L0": l0,
                "L1_pre_rerank": l1_pre,
                "L1": l1,
                "L2": l2,
                "L3": l3,
                "L4": l4,
            },
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
    via_api: bool = False,
    prefer_local: bool = False,
    skip_neo4j: bool = False,
) -> Dict[str, Any]:
    questions = load_golden_questions(golden_path)
    run_id = run_id or create_run_id()
    report_dir = resolve_report_dir(run_id, report_dir)

    async def _run_all() -> List[Dict[str, Any]]:
        results = []
        if via_api:
            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                for idx, question in enumerate(questions, 1):
                    print(f"[{idx}/{len(questions)}] {question['id']} (via-api)...", flush=True)
                    row = await _run_question_via_api(
                        question,
                        client,
                        use_llm=use_llm,
                        use_llm_judge=use_llm_judge,
                        llm_timeout_s=llm_timeout_s,
                    )
                    layers = row.pop("layers", {})
                    if layers:
                        row["snapshot_paths"] = save_layer_snapshots(report_dir, row["id"], layers)
                    results.append(row)
                    print(
                        f"  -> {row.get('status')} ({row.get('e2e_latency_ms')} ms)",
                        flush=True,
                    )
            return results

        for idx, question in enumerate(questions, 1):
            print(f"[{idx}/{len(questions)}] {question['id']}...", flush=True)
            row = await _run_question_pipeline(
                question,
                use_llm=use_llm,
                use_llm_judge=use_llm_judge,
                llm_timeout_s=llm_timeout_s,
                prefer_local=prefer_local,
                skip_neo4j=skip_neo4j,
            )
            layers = row.pop("layers", {})
            if layers:
                row["snapshot_paths"] = save_layer_snapshots(report_dir, row["id"], layers)
            results.append(row)
            print(
                f"  -> {row.get('status')} ({row.get('e2e_latency_ms')} ms)",
                flush=True,
            )
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

    neo4j_vals = [q["neo4j_latency_ms"] for q in per_question if q.get("neo4j_latency_ms")]
    if neo4j_vals:
        aggregate["mean_neo4j_latency_ms"] = round(sum(neo4j_vals) / len(neo4j_vals), 2)

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
        run_metadata_extra={
            "use_llm": use_llm,
            "via_api": via_api,
            "prefer_local": prefer_local,
            "skip_neo4j": skip_neo4j or (not use_llm),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="HSME E2E eval (L0–L4)")
    parser.add_argument("--golden", type=Path, default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM synthesis (dry-run); also skips Neo4j expand",
    )
    parser.add_argument(
        "--via-api",
        action="store_true",
        help="Smoke-test via POST /api/search (HTTP contract path)",
    )
    parser.add_argument(
        "--llm-judge",
        action="store_true",
        help="Run optional LLM-as-judge scoring",
    )
    parser.add_argument("--llm-timeout", type=float, default=30.0)
    parser.add_argument(
        "--prefer-local",
        action="store_true",
        help="Force regex-only local query parsing instead of LLM",
    )
    parser.add_argument(
        "--skip-neo4j",
        action="store_true",
        help="Skip Neo4j expand_graph_context (isolate L0–L2 / VSA)",
    )
    args = parser.parse_args()
    summary = run_e2e_eval(
        golden_path=args.golden,
        run_id=args.run_id,
        use_llm=not args.no_llm,
        use_llm_judge=args.llm_judge,
        llm_timeout_s=args.llm_timeout,
        via_api=args.via_api,
        prefer_local=args.prefer_local,
        skip_neo4j=args.skip_neo4j,
    )
    print(f"E2E eval complete: {summary['artifact_paths']['report_dir']}")
    print(f"Success rate: {summary['aggregate_metrics'].get('success_rate', 0)}")
    if "mean_ttft_s" in summary["aggregate_metrics"]:
        print(f"Mean TTFT: {summary['aggregate_metrics']['mean_ttft_s']} s")
    if "mean_ttfa_s" in summary["aggregate_metrics"]:
        print(f"Mean TTFA: {summary['aggregate_metrics']['mean_ttfa_s']} s")


if __name__ == "__main__":
    main()
