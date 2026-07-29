import pytest
from pydantic import ValidationError

from backend.core.nlp_schemas import (
    NLPExtractionResult,
    validate_nlp_extraction,
    validation_meta_from_error,
)


def test_validate_nlp_extraction_accepts_valid_payload():
    payload = {
        "entities": [
            {"type": "material", "value": "  никель  "},
            {"type": "Property", "value": "pH: 2"},
        ],
        "relations": [
            {
                "source": "электроэкстракция",
                "type": "uses-material",
                "target": "никель",
            }
        ],
    }
    result = validate_nlp_extraction(payload)
    assert result["entities"][0]["type"] == "Material"
    assert result["entities"][0]["value"] == "никель"
    assert result["relations"][0]["type"] == "uses_material"


def test_validate_nlp_extraction_defaults_missing_lists():
    result = validate_nlp_extraction({})
    assert result == {"entities": [], "relations": []}


def test_validate_nlp_extraction_rejects_unknown_entity_type():
    with pytest.raises(ValidationError):
        validate_nlp_extraction(
            {"entities": [{"type": "Planet", "value": "Mars"}], "relations": []}
        )


def test_validate_nlp_extraction_rejects_empty_entity_value():
    with pytest.raises(ValidationError):
        validate_nlp_extraction(
            {"entities": [{"type": "Material", "value": "   "}], "relations": []}
        )


def test_validate_nlp_extraction_rejects_unknown_relation_type():
    with pytest.raises(ValidationError):
        validate_nlp_extraction(
            {
                "entities": [],
                "relations": [
                    {"source": "a", "type": "depends_on", "target": "b"},
                ],
            }
        )


def test_validate_nlp_extraction_rejects_non_object_root():
    with pytest.raises(ValidationError):
        validate_nlp_extraction([])


def test_nlp_extraction_result_model():
    model = NLPExtractionResult.model_validate(
        {
            "entities": [{"type": "Process", "value": "плавка"}],
            "relations": [],
        }
    )
    assert model.entities[0].value == "плавка"


def test_tolerant_keeps_entities_drops_bad_relations():
    payload = {
        "entities": [
            {"type": "Material", "value": "сера"},
            {"type": "Process", "value": "автоклавное окисление"},
        ],
        "relations": [
            {"source": "a", "type": "depends_on", "target": "b"},
        ],
    }
    result = validate_nlp_extraction(payload, strict=False)
    assert len(result["entities"]) == 2
    assert result["relations"] == []
    assert result["_validation"]["dropped_relations"] == 1
    assert result["_validation"]["dropped_entities"] == 0


def test_tolerant_drops_unknown_entity_keeps_valid():
    payload = {
        "entities": [
            {"type": "Planet", "value": "Mars"},
            {"type": "Material", "value": "никель"},
        ],
        "relations": [],
    }
    result = validate_nlp_extraction(payload, strict=False)
    assert len(result["entities"]) == 1
    assert result["entities"][0]["value"] == "никель"
    assert result["_validation"]["dropped_entities"] == 1


def test_tolerant_raises_when_zero_entities_remain():
    with pytest.raises(ValidationError) as exc_info:
        validate_nlp_extraction(
            {
                "entities": [{"type": "Planet", "value": "Mars"}],
                "relations": [],
            },
            strict=False,
        )
    meta = validation_meta_from_error(exc_info.value)
    assert meta["failure_class"] == "tolerant_drop_all"
    assert meta["dropped_entities"] == 1


def test_strict_unchanged_rejects_unknown_relation():
    with pytest.raises(ValidationError):
        validate_nlp_extraction(
            {
                "entities": [{"type": "Material", "value": "Ni"}],
                "relations": [
                    {"source": "a", "type": "depends_on", "target": "b"},
                ],
            },
            strict=True,
        )


def test_safe_relation_aliases_are_normalized():
    payload = {
        "entities": [
            {"type": "Process", "value": "электроэкстракция"},
            {"type": "Material", "value": "никель"},
            {"type": "Facility", "value": "Кольская ГМК"},
        ],
        "relations": [
            {"source": "электроэкстракция", "type": "used_with", "target": "никель"},
            {"source": "электроэкстракция", "type": "used_at", "target": "Кольская ГМК"},
            {"source": "электроэкстракция", "type": "produces", "target": "никель"},
        ],
    }
    result = validate_nlp_extraction(payload, strict=False)
    types = {rel["type"] for rel in result["relations"]}
    assert types == {"uses_material", "located_at", "produces_output"}
    assert result["_validation"]["dropped_relations"] == 0


def test_ambiguous_relation_aliases_still_dropped():
    payload = {
        "entities": [
            {"type": "Process", "value": "плавка"},
            {"type": "Equipment", "value": "печь Ванюкова"},
        ],
        "relations": [
            {"source": "плавка", "type": "uses_equipment", "target": "печь Ванюкова"},
            {"source": "плавка", "type": "used_in", "target": "печь Ванюкова"},
            {"source": "плавка", "type": "developed_by", "target": "Гипроникель"},
            {"source": "плавка", "type": "involved_in", "target": "печь Ванюкова"},
        ],
    }
    result = validate_nlp_extraction(payload, strict=False)
    assert result["relations"] == []
    assert result["_validation"]["dropped_relations"] == 4
