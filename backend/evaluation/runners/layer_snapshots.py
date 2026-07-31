"""Layer snapshot helpers — JSON artifacts per pipeline layer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.services.rerank import RankedHit


def entity_to_dict(entity: Any) -> Dict[str, str]:
    return {"type": entity.type, "value": entity.value}


def build_l0_snapshot(
    entities: List[Any],
    *,
    parse_source: Optional[str] = None,
    via_api: bool = False,
    gate_stage: Optional[str] = None,
    gate_reason: Optional[str] = None,
    gate_signals: Optional[Dict[str, Any]] = None,
    retrieval_empty_reason: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"entities": [entity_to_dict(e) for e in entities]}
    if parse_source:
        payload["parse_source"] = parse_source
    if via_api:
        payload["via_api"] = True
    if gate_stage:
        payload["gate_stage"] = gate_stage
    if gate_reason:
        payload["gate_reason"] = gate_reason
    if gate_signals is not None:
        payload["gate_signals"] = gate_signals
    if retrieval_empty_reason:
        payload["retrieval_empty_reason"] = retrieval_empty_reason
    return payload


def _hit_dict_from_pair(exp: Any, vsa_score: float) -> Dict[str, Any]:
    return {
        "experiment_id": exp.id,
        "name": exp.name,
        "vsa_score": round(float(vsa_score), 4),
        # Backward-compatible alias: always raw VSA, never hybrid.
        "similarity": round(float(vsa_score), 4),
    }


def _hit_dict_from_ranked(hit: RankedHit) -> Dict[str, Any]:
    return {
        "experiment_id": hit.experiment.id,
        "name": hit.experiment.name,
        "vsa_score": round(hit.vsa_score, 4),
        "hybrid_score": round(hit.hybrid_score, 4),
        "similarity": round(hit.vsa_score, 4),
        "score_breakdown": {k: round(v, 4) for k, v in hit.breakdown.items()},
    }


def build_l1_pre_rerank_snapshot(
    hits: Sequence[Tuple[Any, float]],
) -> Dict[str, Any]:
    """Pre-rerank VSA ordering (raw scores only)."""
    return {
        "stage": "pre_rerank",
        "hits": [_hit_dict_from_pair(exp, score) for exp, score in hits],
    }


def build_l1_snapshot(
    hits: Any,
) -> Dict[str, Any]:
    """
    Post-rerank L1 snapshot.

    Accepts either:
    - List[RankedHit] (preferred), or
    - List[Tuple[Experiment, float]] legacy VSA pairs.
    """
    if not hits:
        return {"stage": "post_rerank", "hits": []}
    first = hits[0]
    if isinstance(first, RankedHit):
        return {
            "stage": "post_rerank",
            "hits": [_hit_dict_from_ranked(h) for h in hits],
        }
    return {
        "stage": "post_rerank",
        "hits": [_hit_dict_from_pair(exp, score) for exp, score in hits],
    }


def build_l2_snapshot(
    hits: Any,
    *,
    limit: int,
    geography: Optional[str] = None,
) -> Dict[str, Any]:
    top = list(hits)[:limit]
    if not top:
        return {"limit": limit, "geography_filter": geography, "top_k": []}
    if isinstance(top[0], RankedHit):
        rows = [
            {
                "experiment_id": h.experiment.id,
                "vsa_score": round(h.vsa_score, 4),
                "hybrid_score": round(h.hybrid_score, 4),
                "similarity": round(h.vsa_score, 4),
                "geography": h.experiment.geography,
                "year": h.experiment.year,
            }
            for h in top
        ]
    else:
        rows = [
            {
                "experiment_id": exp.id,
                "vsa_score": round(float(score), 4),
                "similarity": round(float(score), 4),
                "geography": exp.geography,
                "year": exp.year,
            }
            for exp, score in top
        ]
    return {
        "limit": limit,
        "geography_filter": geography,
        "top_k": rows,
    }


def build_l3_snapshot(counterfactuals: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "counterfactuals": [
            {
                "experiment_id": cf["experiment"].id,
                "difference": cf.get("difference"),
                "effects_count": len(cf.get("effects") or []),
            }
            for cf in counterfactuals
        ]
    }


def build_l4_snapshot(
    *,
    answer: Optional[str],
    e2e_latency_ms: float,
    vsa_latency_ms: Optional[float] = None,
    neo4j_latency_ms: Optional[float] = None,
    ttft_s: Optional[float] = None,
    ttfa_s: Optional[float] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "answer_preview": (answer or "")[:500],
        "answer_length": len(answer or ""),
        "e2e_latency_ms": round(e2e_latency_ms, 2),
        "vsa_latency_ms": vsa_latency_ms,
        "neo4j_latency_ms": neo4j_latency_ms,
        "ttft_s": round(ttft_s, 4) if ttft_s is not None else None,
        "ttfa_s": round(ttfa_s, 4) if ttfa_s is not None else None,
        "error": error,
    }


def save_layer_snapshots(
    report_dir: Path,
    question_id: str,
    layers: Dict[str, Dict[str, Any]],
) -> Dict[str, str]:
    """Write per-layer JSON files; return paths."""
    snap_dir = report_dir / "snapshots" / question_id
    snap_dir.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, str] = {}
    for layer_name, payload in layers.items():
        out = snap_dir / f"{layer_name}.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        paths[layer_name] = str(out)
    return paths
