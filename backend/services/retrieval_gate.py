"""No-Evidence / OOD / low-confidence gates for retrieval (runtime, not golden category).

Two layers (papers 1.1 + 1.4, heuristic proxy — no PCA training):
  1. Scope / OOD gate — is the query in the corpus domain?
  2. Confidence guardrails — is retrieval evidence strong enough to answer?
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.core.models import Entity, Experiment
from backend.services.rerank import _entity_overlap, _normalize

# --- Thresholds (single place; tune via eval, not scattered ifs) ---
MIN_TOP_VSA_SCORE = 0.05
MIN_ENTITY_VALUE_LEN = 3
# Confidence: below this top-1, refuse (hard floor above MIN_TOP_VSA_SCORE).
LOW_CONFIDENCE_TOP_VSA = 0.08
# Scope/OOD: modest VSA + zero overlap → out of corpus affinity.
OOD_MODEST_TOP_VSA = 0.25
# Confidence: tiny margin between #1 and #2 with near-zero overlap → refuse.
WEAK_MARGIN = 0.02
WEAK_OVERLAP_FOR_MARGIN = 0.05
# Confidence: mono-family noisy top-k (only when VSA is clearly weak).
MONO_FAMILY_TOP_VSA_CAP = 0.10
# Clarification: single vague in-domain entity, middling scores.
CLARIFY_MAX_ENTITIES = 1
CLARIFY_TOP_VSA_LO = 0.08
CLARIFY_TOP_VSA_HI = 0.15

DOMAIN_TYPES = frozenset({"Material", "Process", "Equipment", "Property", "Facility"})
NON_DOMAIN_TYPES = frozenset({"Expert", "Publication"})

# Ultra-generic fillers that look "domain-typed" but are off-topic / useless.
GENERIC_ENTITY_VALUES = frozenset(
    {
        "завод",
        "оборудование",
        "руда",
        "руды",
        "рудой",
        "автор",
        "мосты",
        "пицца",
        "погода",
        "аргон",
        "метан",
        "пар",
        "ванна",
        "щелок",
        "экстракт",
        "электрум",
        "электроды",
        "катоды",
        "примеси",
        "рудник",
        "рудное",
        "олеум",
        "бор",
    }
)

NO_EVIDENCE_ANSWER = "Нет релевантных экспериментов для анализа."


@dataclass
class GateDecision:
    """Structured retrieval gate outcome for runtime + eval observability."""

    should_empty: bool
    reason: str = ""
    stage: str = ""  # "scope" | "confidence" | ""
    signals: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def sanitize_query_entities(entities: Sequence[Entity]) -> List[Entity]:
    """Drop ultra-short / empty entity values that pollute VSA (e.g. 'в', 'с', 'ма')."""
    cleaned: List[Entity] = []
    seen: set[str] = set()
    for ent in entities:
        value = _normalize(ent.value or "")
        if len(value) < MIN_ENTITY_VALUE_LEN:
            continue
        key = f"{ent.type}:{value}"
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(
            Entity(type=ent.type, value=ent.value.strip() if ent.value else ent.value)
        )
    return cleaned


def is_weak_parse(entities: Sequence[Entity]) -> bool:
    """Heuristic: parse is too weak to justify non-empty retrieval."""
    if not entities:
        return True
    if not any(e.type in DOMAIN_TYPES for e in entities):
        return True
    lengths = [len(_normalize(e.value or "")) for e in entities]
    if lengths and (sum(lengths) / len(lengths)) < 4.0 and len(entities) >= 3:
        return True
    return False


def _source_family(exp_id: str) -> str:
    """Proxy document family from experiment id (e.g. EXP-ОИП-03-2025-11 → EXP-ОИП-03)."""
    parts = (exp_id or "").split("-")
    if len(parts) >= 3:
        return "-".join(parts[:3])
    return exp_id or ""


def _is_generic_value(value: str) -> bool:
    return _normalize(value) in GENERIC_ENTITY_VALUES


def compute_scope_signals(entities: Sequence[Entity]) -> Dict[str, Any]:
    """Cheap query-level domain/OOD signals (paper 1.1 proxy, no PCA)."""
    n = len(entities)
    if n == 0:
        return {
            "sanitized_entity_count": 0,
            "domain_type_count": 0,
            "domain_type_ratio": 0.0,
            "generic_entity_count": 0,
            "generic_entity_ratio": 0.0,
            "mean_entity_value_len": 0.0,
            "non_domain_only": True,
        }
    domain_count = sum(1 for e in entities if e.type in DOMAIN_TYPES)
    generic_count = sum(1 for e in entities if _is_generic_value(e.value or ""))
    lengths = [len(_normalize(e.value or "")) for e in entities]
    return {
        "sanitized_entity_count": n,
        "domain_type_count": domain_count,
        "domain_type_ratio": domain_count / n,
        "generic_entity_count": generic_count,
        "generic_entity_ratio": generic_count / n,
        "mean_entity_value_len": sum(lengths) / len(lengths),
        "non_domain_only": domain_count == 0,
    }


def compute_confidence_signals(
    entities: Sequence[Entity],
    hits: Sequence[Tuple[Experiment, float]],
) -> Dict[str, Any]:
    """Post-retrieval confidence signals (paper 1.4 guardrails)."""
    if not hits:
        return {
            "top1_vsa": 0.0,
            "top5_mean_vsa": 0.0,
            "top1_top2_margin": 0.0,
            "max_entity_overlap": 0.0,
            "top5_unique_source_count": 0,
            "hit_count": 0,
            "has_conflicting_versions": False,
        }
    top_k = list(hits[:5])
    scores = [float(s) for _, s in top_k]
    top1 = scores[0]
    top2 = scores[1] if len(scores) > 1 else top1
    max_overlap = max((_entity_overlap(entities, exp) for exp, _ in top_k), default=0.0)
    families = {_source_family(exp.id) for exp, _ in top_k}
    return {
        "top1_vsa": top1,
        "top5_mean_vsa": sum(scores) / len(scores),
        "top1_top2_margin": top1 - top2,
        "max_entity_overlap": max_overlap,
        "top5_unique_source_count": len(families),
        "hit_count": len(hits),
        "has_conflicting_versions": False,
    }


def evaluate_retrieval_gate(
    entities: Sequence[Entity],
    hits: Sequence[Tuple[Experiment, float]],
) -> GateDecision:
    """
    Hierarchical abstention: scope (1.1) then confidence (1.4).

    Returns a structured decision; never raises.
    """
    scope = compute_scope_signals(entities)
    conf = compute_confidence_signals(entities, hits)
    signals: Dict[str, Any] = {**scope, **conf}

    # --- Stage: scope ---
    if not entities:
        return GateDecision(
            should_empty=True,
            reason="no_entities",
            stage="scope",
            signals=signals,
        )
    if is_weak_parse(entities):
        return GateDecision(
            should_empty=True,
            reason="weak_parse",
            stage="scope",
            signals=signals,
        )
    non_domain_ratio = 1.0 - float(scope["domain_type_ratio"])
    # Expert/Publication-dominated parse + weak VSA → OOD (e.g. pizza → Experts + аргон).
    if (
        non_domain_ratio >= 0.5
        and conf["hit_count"] > 0
        and conf["top1_vsa"] < 0.12
    ):
        return GateDecision(
            should_empty=True,
            reason="ood_scope",
            stage="scope",
            signals=signals,
        )
    # Generic domain-typed fillers (пицца/завод/аргон) with weak corpus affinity.
    if (
        scope["generic_entity_count"] >= 1
        and scope["domain_type_ratio"] <= 0.5
        and conf["top1_vsa"] < 0.15
        and scope["sanitized_entity_count"] <= 6
    ):
        return GateDecision(
            should_empty=True,
            reason="ood_scope",
            stage="scope",
            signals=signals,
        )
    if (
        scope["generic_entity_ratio"] >= 0.5
        and scope["sanitized_entity_count"] <= 4
        and conf["max_entity_overlap"] <= 0.0
    ):
        return GateDecision(
            should_empty=True,
            reason="ood_scope",
            stage="scope",
            signals=signals,
        )
    # Weak corpus affinity: modest VSA + zero entity overlap → OOD.
    if conf["hit_count"] > 0 and conf["max_entity_overlap"] <= 0.0 and conf["top1_vsa"] < OOD_MODEST_TOP_VSA:
        return GateDecision(
            should_empty=True,
            reason="ood_scope",
            stage="scope",
            signals=signals,
        )

    # --- Stage: confidence ---
    if not hits:
        return GateDecision(
            should_empty=True,
            reason="no_hits",
            stage="confidence",
            signals=signals,
        )
    if conf["top1_vsa"] < MIN_TOP_VSA_SCORE:
        return GateDecision(
            should_empty=True,
            reason="low_confidence",
            stage="confidence",
            signals=signals,
        )
    # Hard floor: very low top-1 is never answerable, even with incidental overlap.
    if conf["top1_vsa"] < LOW_CONFIDENCE_TOP_VSA:
        return GateDecision(
            should_empty=True,
            reason="low_confidence",
            stage="confidence",
            signals=signals,
        )
    if (
        conf["top1_top2_margin"] < WEAK_MARGIN
        and conf["max_entity_overlap"] < WEAK_OVERLAP_FOR_MARGIN
        and conf["top1_vsa"] < 0.20
    ):
        return GateDecision(
            should_empty=True,
            reason="low_confidence",
            stage="confidence",
            signals=signals,
        )
    if (
        conf["top5_unique_source_count"] <= 1
        and conf["top1_vsa"] < MONO_FAMILY_TOP_VSA_CAP
        and conf["max_entity_overlap"] < 0.20
        and conf["hit_count"] >= 3
    ):
        return GateDecision(
            should_empty=True,
            reason="low_confidence",
            stage="confidence",
            signals=signals,
        )
    # Ambiguous single-entity in-domain query — still empty, distinct reason.
    if (
        scope["sanitized_entity_count"] <= CLARIFY_MAX_ENTITIES
        and CLARIFY_TOP_VSA_LO <= conf["top1_vsa"] < CLARIFY_TOP_VSA_HI
        and conf["max_entity_overlap"] < 0.20
    ):
        return GateDecision(
            should_empty=True,
            reason="needs_clarification",
            stage="confidence",
            signals=signals,
        )

    return GateDecision(
        should_empty=False,
        reason="",
        stage="",
        signals=signals,
    )


def should_return_empty_retrieval(
    entities: Sequence[Entity],
    hits: Sequence[Tuple[Experiment, float]],
) -> bool:
    """Compat wrapper — prefer evaluate_retrieval_gate() for reason codes."""
    return evaluate_retrieval_gate(entities, hits).should_empty
