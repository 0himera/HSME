"""Layer snapshot helpers — JSON artifacts per pipeline layer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def entity_to_dict(entity: Any) -> Dict[str, str]:
    return {"type": entity.type, "value": entity.value}


def build_l0_snapshot(entities: List[Any]) -> Dict[str, Any]:
    return {"entities": [entity_to_dict(e) for e in entities]}


def build_l1_snapshot(hits: List[Any]) -> Dict[str, Any]:
    return {
        "hits": [
            {"experiment_id": exp.id, "name": exp.name, "similarity": round(score, 4)}
            for exp, score in hits
        ]
    }


def build_l2_snapshot(
    hits: List[Any],
    *,
    limit: int,
    geography: Optional[str] = None,
) -> Dict[str, Any]:
    top = hits[:limit]
    return {
        "limit": limit,
        "geography_filter": geography,
        "top_k": [
            {
                "experiment_id": exp.id,
                "similarity": round(score, 4),
                "geography": exp.geography,
                "year": exp.year,
            }
            for exp, score in top
        ],
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
