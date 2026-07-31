"""Tests for No-Evidence / OOD / low-confidence retrieval gate."""

from __future__ import annotations

from backend.core.models import Entity, Experiment
from backend.services.retrieval_gate import (
    evaluate_retrieval_gate,
    is_weak_parse,
    sanitize_query_entities,
    should_return_empty_retrieval,
)


def _exp(exp_id: str, materials: list[str] | None = None) -> Experiment:
    return Experiment(
        id=exp_id,
        name=exp_id,
        input_entities=[Entity(type="Material", value=m) for m in (materials or ["Nickel"])],
        process_entities=[Entity(type="Process", value="Electrowinning")],
        output_entities=[],
        relations=[],
    )


def test_sanitize_drops_short_tokens():
    ents = [
        Entity(type="Material", value="Ni"),
        Entity(type="Process", value="в"),
        Entity(type="Material", value="Никель"),
        Entity(type="Process", value="электроэкстракция"),
    ]
    cleaned = sanitize_query_entities(ents)
    values = {e.value for e in cleaned}
    assert "в" not in values
    assert "Ni" not in values  # len 2
    assert "Никель" in values


def test_weak_parse_empty_and_non_domain():
    assert is_weak_parse([]) is True
    assert is_weak_parse([Entity(type="Expert", value="Ivanov")]) is True
    assert (
        is_weak_parse(
            [
                Entity(type="Material", value="Никель"),
                Entity(type="Process", value="электроэкстракция"),
            ]
        )
        is False
    )


def test_gate_empty_on_weak_or_low_vsa():
    assert should_return_empty_retrieval([], []) is True
    hits = [(_exp("EXP-1"), 0.02)]
    ents = [Entity(type="Material", value="пицца")]
    assert should_return_empty_retrieval(ents, hits) is True


def test_gate_empty_when_no_overlap_and_modest_vsa():
    ents = [Entity(type="Material", value="пицца")]
    hits = [(_exp("ОИП-01", materials=["Никель"]), 0.20)]
    assert should_return_empty_retrieval(ents, hits) is True


def test_gate_allows_strong_vsa_with_overlap():
    ents = [
        Entity(type="Material", value="Nickel"),
        Entity(type="Process", value="Electrowinning"),
    ]
    hits = [(_exp("EXP-NI-01", materials=["Nickel"]), 0.55)]
    assert should_return_empty_retrieval(ents, hits) is False


def test_evaluate_no_entities_reason():
    d = evaluate_retrieval_gate([], [])
    assert d.should_empty is True
    assert d.reason == "no_entities"
    assert d.stage == "scope"
    assert d.signals["sanitized_entity_count"] == 0


def test_evaluate_weak_parse_reason():
    d = evaluate_retrieval_gate([Entity(type="Expert", value="Ivanov")], [])
    assert d.should_empty is True
    assert d.reason == "weak_parse"
    assert d.stage == "scope"


def test_evaluate_ood_scope_generic_pizza():
    ents = [Entity(type="Material", value="пицца")]
    hits = [(_exp("ОИП-01", materials=["Никель"]), 0.20)]
    d = evaluate_retrieval_gate(ents, hits)
    assert d.should_empty is True
    assert d.reason == "ood_scope"
    assert d.stage == "scope"
    assert d.signals["max_entity_overlap"] == 0.0
    assert "top1_vsa" in d.signals


def test_evaluate_ood_scope_expert_dominated_argon():
    """q009-style parse: Experts + generic Material with weak VSA."""
    ents = [
        Entity(type="Expert", value="и. а. марки"),
        Entity(type="Expert", value="марки и. а."),
        Entity(type="Material", value="аргон"),
    ]
    hits = [
        (_exp("EXP-ОИП-07-2022-06", materials=["аргон"]), 0.068),
        (_exp("EXP-ОИП-07-2022-08", materials=["цинк"]), 0.060),
    ]
    d = evaluate_retrieval_gate(ents, hits)
    assert d.should_empty is True
    assert d.reason in {"ood_scope", "low_confidence"}
    assert d.stage in {"scope", "confidence"}


def test_evaluate_low_confidence_very_low_top_vsa():
    ents = [
        Entity(type="Material", value="Nickel"),
        Entity(type="Process", value="Electrowinning"),
    ]
    hits = [(_exp("EXP-NI-01", materials=["Nickel"]), 0.03)]
    d = evaluate_retrieval_gate(ents, hits)
    assert d.should_empty is True
    assert d.reason == "low_confidence"
    assert d.stage == "confidence"


def test_evaluate_strong_in_scope_passes():
    ents = [
        Entity(type="Material", value="Nickel"),
        Entity(type="Process", value="Electrowinning"),
    ]
    hits = [
        (_exp("EXP-NI-01", materials=["Nickel"]), 0.55),
        (_exp("EXP-NI-02", materials=["Nickel"]), 0.40),
    ]
    d = evaluate_retrieval_gate(ents, hits)
    assert d.should_empty is False
    assert d.reason == ""
    assert d.signals["max_entity_overlap"] > 0
    assert d.signals["top1_vsa"] == 0.55


def test_gate_decision_as_dict():
    d = evaluate_retrieval_gate([], [])
    payload = d.as_dict()
    assert payload["should_empty"] is True
    assert payload["reason"] == "no_entities"
    assert isinstance(payload["signals"], dict)
