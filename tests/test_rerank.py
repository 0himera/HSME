"""Tests for hybrid VSA reranker (Gap Этап 1 / Stage 9.1 demotion fix)."""

from __future__ import annotations

from backend.core.models import Entity, Experiment
from backend.services.rerank import RankedHit, hybrid_rerank, hybrid_score


def _exp(
    exp_id: str,
    *,
    materials: list[str] | None = None,
    process: str | None = None,
    confidence: float = 0.5,
    source_type: str = "Article",
    evidence: list[str] | None = None,
) -> Experiment:
    return Experiment(
        id=exp_id,
        name=exp_id,
        input_entities=[Entity(type="Material", value=m) for m in (materials or [])],
        process_entities=[Entity(type="Process", value=process)] if process else [],
        output_entities=[Entity(type="Property", value="Yield: 90%")],
        relations=[],
        evidence=evidence or [],
        confidence=confidence,
        source_type=source_type,
    )


def test_hybrid_rerank_prefers_entity_overlap_over_raw():
    query = [
        Entity(type="Material", value="Nickel"),
        Entity(type="Process", value="Electrowinning"),
    ]
    raw = _exp("EXP-RAW-99", materials=["Zinc"], process="Leaching", confidence=0.9)
    good = _exp(
        "EXP-NI-01",
        materials=["Nickel"],
        process="Electrowinning",
        confidence=0.8,
        evidence=["doc.pdf"],
    )
    hits = [(raw, 0.95), (good, 0.70)]
    ranked = hybrid_rerank(query, hits)
    assert isinstance(ranked[0], RankedHit)
    assert ranked[0].experiment.id == "EXP-NI-01"
    # similarity / vsa_score must stay raw VSA, never hybrid overwrite
    assert ranked[0].vsa_score == 0.70
    assert ranked[0].hybrid_score != ranked[0].vsa_score


def test_hybrid_rerank_graph_support_boosts():
    query = [Entity(type="Material", value="Nickel")]
    a = _exp("EXP-A", materials=["Nickel"], confidence=0.5)
    b = _exp("EXP-B", materials=["Nickel"], confidence=0.5)
    graph = {
        "paths": [
            {
                "experiment_id": "EXP-B",
                "nodes": [{"name": "p.pdf", "type": "Publication"}],
                "relations": ["EVIDENCE_FROM"],
            }
        ],
        "publications": ["p.pdf"],
        "experts": [],
        "contradictions": [],
    }
    ranked = hybrid_rerank(query, [(a, 0.8), (b, 0.8)], graph_context=graph)
    assert ranked[0].experiment.id == "EXP-B"
    assert hybrid_score(query, b, 0.8, graph) > hybrid_score(query, a, 0.8, None)


def test_hybrid_rerank_empty():
    assert hybrid_rerank([], []) == []


def test_hybrid_rerank_preserves_vsa_order_when_gold_clearly_ahead():
    """Regression q007/q008: do not demote clear VSA gold out of top-5.

    Gold sits at VSA #2/#4 with a healthy margin; distractors may have
    slightly better secondary signals but must not leapfrog gold when W_VSA dominates.
    """
    query = [
        Entity(type="Material", value="Copper"),
        Entity(type="Process", value="Electrowinning"),
        Entity(type="Facility", value="Long Harbour"),
    ]
    gold = _exp(
        "EXP-CU-01",
        materials=["Copper"],
        process="Electrowinning",
        confidence=0.7,
        evidence=["long_harbour.pdf"],
    )
    distractors = [
        _exp(f"ОИП-{i:02d}", materials=["Copper"], process="Electrowinning", confidence=0.95, evidence=["a.pdf", "b.pdf"])
        for i in range(1, 6)
    ]
    # VSA order: d1, gold, d2.. — gold clearly ahead of most distractors
    hits = [
        (distractors[0], 0.88),
        (gold, 0.86),
        (distractors[1], 0.74),
        (distractors[2], 0.73),
        (distractors[3], 0.72),
        (distractors[4], 0.71),
    ]
    ranked = hybrid_rerank(query, hits)
    top5_ids = [h.experiment.id for h in ranked[:5]]
    assert "EXP-CU-01" in top5_ids
    # Gold must not fall below its VSA-adjacent band (still top-3 after mild secondary nudges)
    assert top5_ids.index("EXP-CU-01") <= 2
    # Separate score fields always present
    for h in ranked:
        assert "entity_overlap" in h.breakdown
        assert h.as_result_dict()["similarity"] == h.vsa_score
        assert h.as_result_dict()["hybrid_score"] == round(h.hybrid_score, 6)


def test_hybrid_rerank_preserves_hl_gold_in_top5():
    """Regression q008-style: HL gold in VSA top-5 stays in post-rerank top-5."""
    query = [
        Entity(type="Process", value="Heap Leaching"),
        Entity(type="Material", value="Ore"),
    ]
    gold = _exp(
        "EXP-HL-02",
        materials=["Ore"],
        process="Heap Leaching",
        confidence=0.6,
    )
    noise = [
        _exp(f"ОИП-HL-{i}", materials=["Ore"], process="Leaching", confidence=0.9)
        for i in range(6)
    ]
    hits = [
        (noise[0], 0.90),
        (noise[1], 0.85),
        (noise[2], 0.80),
        (gold, 0.78),
        (noise[3], 0.70),
        (noise[4], 0.65),
        (noise[5], 0.60),
    ]
    pre_top5 = [exp.id for exp, _ in hits[:5]]
    assert "EXP-HL-02" in pre_top5
    ranked = hybrid_rerank(query, hits)
    post_top5 = [h.experiment.id for h in ranked[:5]]
    assert "EXP-HL-02" in post_top5
