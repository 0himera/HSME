"""Hybrid rule-based reranker over VSA hits (Gap Этап 1 / HiGMem compact evidence)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.core.models import Entity, Experiment

# Calibrated to preserve VSA ordering (q007/q008 demotion fix):
# raw VSA must dominate; secondary signals only nudge within close VSA bands.
W_VSA = 0.72
W_ENTITY = 0.12
W_METRIC = 0.05
W_GRAPH = 0.05
W_SOURCE = 0.03
W_RAW_PENALTY = 0.15


@dataclass(frozen=True)
class RankedHit:
    """Single retrieval hit with separate VSA and hybrid scores (never overwrite VSA)."""

    experiment: Experiment
    vsa_score: float
    hybrid_score: float
    breakdown: Dict[str, float]

    def as_result_dict(self) -> Dict[str, Any]:
        """API/eval payload: similarity stays VSA for backward-compatible thresholds."""
        return {
            "experiment": self.experiment,
            "similarity": self.vsa_score,
            "vsa_score": round(self.vsa_score, 6),
            "hybrid_score": round(self.hybrid_score, 6),
            "score_breakdown": {k: round(v, 6) for k, v in self.breakdown.items()},
        }


def _normalize(value: str) -> str:
    return " ".join(value.lower().split())


def _entity_keys(entities: Sequence[Entity]) -> set[str]:
    return {_normalize(f"{e.type}:{e.value}") for e in entities}


def _experiment_entities(exp: Experiment) -> List[Entity]:
    return list(exp.get_all_entities())


def _entity_overlap(query_entities: Sequence[Entity], exp: Experiment) -> float:
    if not query_entities:
        return 0.0
    q = _entity_keys(query_entities)
    e = _entity_keys(_experiment_entities(exp))
    if not q:
        return 0.0
    return len(q & e) / len(q)


def _metric_overlap(query_entities: Sequence[Entity], exp: Experiment) -> float:
    q_props = {
        _normalize(e.value.split(":", 1)[0])
        for e in query_entities
        if e.type == "Property"
    }
    if not q_props:
        return 0.0
    e_props = {
        _normalize(e.value.split(":", 1)[0]) if ":" in e.value else _normalize(e.value)
        for e in _experiment_entities(exp)
        if e.type == "Property"
    }
    return len(q_props & e_props) / len(q_props)


def _source_quality(exp: Experiment) -> float:
    score = 0.0
    st = (exp.source_type or "").lower()
    if st in {"article", "patent", "gost", "report"}:
        score += 0.6
    elif st:
        score += 0.3
    if exp.confidence is not None:
        score += 0.4 * max(0.0, min(1.0, float(exp.confidence)))
    if exp.evidence:
        score += min(0.2, 0.05 * len(exp.evidence))
    return min(1.0, score)


def _raw_noise_penalty(exp: Experiment) -> float:
    exp_id = (exp.id or "").upper()
    if exp_id.startswith("EXP-RAW") or "RAW" in exp_id.split("-")[:2]:
        return 1.0
    return 0.0


def _graph_support_for_exp(
    exp_id: str, graph_context: Optional[Dict[str, Any]]
) -> float:
    """Per-experiment graph support only — never apply aggregate pubs/experts to all hits."""
    if not graph_context or graph_context.get("neo4j_error"):
        return 0.0
    paths = [
        p
        for p in (graph_context.get("paths") or [])
        if isinstance(p, dict) and p.get("experiment_id") == exp_id
    ]
    if not paths:
        return 0.0
    score = 0.5
    rels = {r for p in paths for r in (p.get("relations") or [])}
    if "EVIDENCE_FROM" in rels:
        score += 0.3
    if any(str(r).startswith("HAS_") for r in rels):
        score += 0.2
    return min(1.0, score)


def hybrid_score_breakdown(
    query_entities: Sequence[Entity],
    exp: Experiment,
    vsa_score: float,
    graph_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    """Component scores used by hybrid_rerank (for debug/eval observability)."""
    entity = _entity_overlap(query_entities, exp)
    metric = _metric_overlap(query_entities, exp)
    graph = _graph_support_for_exp(exp.id, graph_context)
    source = _source_quality(exp)
    raw_penalty = _raw_noise_penalty(exp)
    hybrid = (
        W_VSA * float(vsa_score)
        + W_ENTITY * entity
        + W_METRIC * metric
        + W_GRAPH * graph
        + W_SOURCE * source
        - W_RAW_PENALTY * raw_penalty
    )
    return {
        "vsa_score": float(vsa_score),
        "entity_overlap": entity,
        "metric_overlap": metric,
        "graph_support": graph,
        "source_quality": source,
        "raw_penalty": raw_penalty,
        "hybrid_score": hybrid,
    }


def hybrid_score(
    query_entities: Sequence[Entity],
    exp: Experiment,
    vsa_score: float,
    graph_context: Optional[Dict[str, Any]] = None,
) -> float:
    """Composite score in roughly [-0.15, 1.0] range."""
    return hybrid_score_breakdown(query_entities, exp, vsa_score, graph_context)[
        "hybrid_score"
    ]


def hybrid_rerank(
    query_entities: Sequence[Entity],
    hits: List[Tuple[Experiment, float]],
    graph_context: Optional[Dict[str, Any]] = None,
) -> List[RankedHit]:
    """Re-order VSA hits by hybrid score; preserves raw vsa_score on each hit."""
    if not hits:
        return []
    ranked: List[RankedHit] = []
    for exp, vsa in hits:
        breakdown = hybrid_score_breakdown(query_entities, exp, vsa, graph_context)
        ranked.append(
            RankedHit(
                experiment=exp,
                vsa_score=float(vsa),
                hybrid_score=float(breakdown["hybrid_score"]),
                breakdown={
                    "entity_overlap": breakdown["entity_overlap"],
                    "metric_overlap": breakdown["metric_overlap"],
                    "graph_support": breakdown["graph_support"],
                    "source_quality": breakdown["source_quality"],
                    "raw_penalty": breakdown["raw_penalty"],
                },
            )
        )
    ranked.sort(key=lambda h: h.hybrid_score, reverse=True)
    return ranked


def ranked_to_legacy_pairs(ranked: List[RankedHit]) -> List[Tuple[Experiment, float]]:
    """Compat helper: (experiment, vsa_score) — never substitute hybrid for VSA."""
    return [(h.experiment, h.vsa_score) for h in ranked]
