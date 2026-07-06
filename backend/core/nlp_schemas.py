"""Pydantic schemas for NLP extraction LLM responses."""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

ENTITY_TYPES = (
    "Material",
    "Process",
    "Equipment",
    "Property",
    "Expert",
    "Facility",
    "Publication",
)
EntityType = Literal[
    "Material",
    "Process",
    "Equipment",
    "Property",
    "Expert",
    "Facility",
    "Publication",
]

RELATION_TYPES = (
    "uses_material",
    "operates_at_condition",
    "produces_output",
    "located_at",
    "described_in",
    "validated_by",
    "contradicts",
)
RelationType = Literal[
    "uses_material",
    "operates_at_condition",
    "produces_output",
    "located_at",
    "described_in",
    "validated_by",
    "contradicts",
]

_ENTITY_TYPE_LOOKUP = {name.lower(): name for name in ENTITY_TYPES}
_RELATION_TYPE_LOOKUP = {name.lower(): name for name in RELATION_TYPES}


class ExtractedEntity(BaseModel):
    type: EntityType
    value: str = Field(min_length=1)

    @field_validator("type", mode="before")
    @classmethod
    def normalize_entity_type(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise TypeError("entity type must be a string")
        normalized = _ENTITY_TYPE_LOOKUP.get(value.strip().lower())
        if normalized is None:
            raise ValueError(f"unsupported entity type: {value!r}")
        return normalized

    @field_validator("value", mode="before")
    @classmethod
    def normalize_value(cls, value: Any) -> str:
        if not isinstance(value, str):
            value = str(value)
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("entity value must not be empty")
        return cleaned


class ExtractedRelation(BaseModel):
    source: str = Field(min_length=1)
    type: RelationType
    target: str = Field(min_length=1)

    @field_validator("type", mode="before")
    @classmethod
    def normalize_relation_type(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise TypeError("relation type must be a string")
        cleaned = value.strip().lower().replace(" ", "_").replace("-", "_")
        normalized = _RELATION_TYPE_LOOKUP.get(cleaned)
        if normalized is None:
            raise ValueError(f"unsupported relation type: {value!r}")
        return normalized

    @field_validator("source", "target", mode="before")
    @classmethod
    def normalize_endpoint(cls, value: Any) -> str:
        if not isinstance(value, str):
            value = str(value)
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("relation endpoint must not be empty")
        return cleaned


class NLPExtractionResult(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)

    @field_validator("entities", "relations", mode="before")
    @classmethod
    def default_missing_lists(cls, value: Any) -> list[Any]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("expected a list")
        return value


def _validate_tolerant(payload: dict[str, Any]) -> dict[str, Any]:
    entities_raw = payload.get("entities") or []
    relations_raw = payload.get("relations") or []
    if not isinstance(entities_raw, list) or not isinstance(relations_raw, list):
        raise ValidationError.from_exception_data(
            "NLPExtractionResult",
            [{"type": "list_type", "loc": ("entities",), "msg": "expected a list", "input": entities_raw}],
        )

    entities: list[dict[str, Any]] = []
    dropped_entities = 0
    for item in entities_raw:
        try:
            entities.append(ExtractedEntity.model_validate(item).model_dump(mode="python"))
        except ValidationError:
            dropped_entities += 1

    relations: list[dict[str, Any]] = []
    dropped_relations = 0
    for item in relations_raw:
        try:
            relations.append(ExtractedRelation.model_validate(item).model_dump(mode="python"))
        except ValidationError:
            dropped_relations += 1

    if dropped_entities or dropped_relations:
        logger.warning(
            "Tolerant validation dropped entities=%d relations=%d",
            dropped_entities,
            dropped_relations,
        )

    if not entities:
        raise ValidationError.from_exception_data(
            "NLPExtractionResult",
            [
                {
                    "type": "value_error",
                    "loc": ("entities",),
                    "msg": "no valid entities remain",
                    "input": entities_raw,
                    "ctx": {"error": ValueError("no valid entities remain")},
                }
            ],
        )

    return {"entities": entities, "relations": relations}


def validate_nlp_extraction(payload: Any, *, strict: bool = True) -> dict[str, Any]:
    """Validate LLM extraction JSON and return a plain dict for ingestion."""
    if strict:
        return NLPExtractionResult.model_validate(payload).model_dump(mode="python")
    if not isinstance(payload, dict):
        raise ValidationError.from_exception_data(
            "NLPExtractionResult",
            [{"type": "dict_type", "loc": (), "msg": "expected a dict", "input": payload}],
        )
    return _validate_tolerant(payload)
