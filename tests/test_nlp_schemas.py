import pytest
from pydantic import ValidationError

from backend.core.nlp_schemas import (
    NLPExtractionResult,
    validate_nlp_extraction,
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


def test_tolerant_raises_when_zero_entities_remain():
    with pytest.raises(ValidationError):
        validate_nlp_extraction(
            {
                "entities": [{"type": "Planet", "value": "Mars"}],
                "relations": [],
            },
            strict=False,
        )


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
