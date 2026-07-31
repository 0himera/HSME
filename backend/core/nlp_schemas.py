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

# Safe aliases only — ambiguous LLM inventions stay dropped (no ontology expansion).
_RELATION_ALIASES = {
    "used_at": "located_at",
    "located_in": "located_at",
    "located_on": "located_at",
    "used_with": "uses_material",
    "uses": "uses_material",
    "has_condition": "operates_at_condition",
    "operates_at": "operates_at_condition",
    "operates_under": "operates_at_condition",
    "produces": "produces_output",
    "produces_result": "produces_output",
    "described_by": "described_in",
    "documented_in": "described_in",
    "mentioned_in": "described_in",
}


def normalize_relation_type_name(value: Any) -> str:
    """Normalize / alias relation type to whitelist; raise if unsupported."""
    if not isinstance(value, str):
        raise TypeError("relation type must be a string")
    cleaned = value.strip().lower().replace(" ", "_").replace("-", "_")
    cleaned = _RELATION_ALIASES.get(cleaned, cleaned)
    normalized = _RELATION_TYPE_LOOKUP.get(cleaned)
    if normalized is None:
        raise ValueError(f"unsupported relation type: {value!r}")
    return normalized


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
        return normalize_relation_type_name(value)

    @field_validator("source", "target", mode="before")
    @classmethod
    def normalize_endpoint(cls, value: Any) -> str:
        if not isinstance(value, str):
            value = str(value)
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("relation endpoint must not be empty")
        return cleaned


class QueryParseResult(BaseModel):
    """Structured L0 query parse output."""

    entities: list[ExtractedEntity] = Field(default_factory=list)

    @field_validator("entities", mode="before")
    @classmethod
    def default_missing_entities(cls, value: Any) -> list[Any]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("expected a list")
        return value


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


def _preview(value: Any, limit: int = 240) -> str:
    text = value if isinstance(value, str) else repr(value)
    text = text.replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


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
    entity_drop_reasons: list[str] = []
    for item in entities_raw:
        try:
            entities.append(ExtractedEntity.model_validate(item).model_dump(mode="python"))
        except ValidationError as exc:
            dropped_entities += 1
            if len(entity_drop_reasons) < 5:
                entity_drop_reasons.append(_preview(exc.errors()[0].get("msg", "invalid entity"), 120))

    relations: list[dict[str, Any]] = []
    dropped_relations = 0
    relation_drop_reasons: list[str] = []
    for item in relations_raw:
        try:
            relations.append(ExtractedRelation.model_validate(item).model_dump(mode="python"))
        except ValidationError as exc:
            dropped_relations += 1
            if len(relation_drop_reasons) < 5:
                relation_drop_reasons.append(_preview(exc.errors()[0].get("msg", "invalid relation"), 120))

    validation_meta = {
        "dropped_entities": dropped_entities,
        "dropped_relations": dropped_relations,
        "entity_drop_reasons": entity_drop_reasons,
        "relation_drop_reasons": relation_drop_reasons,
        "raw_entity_count": len(entities_raw),
        "raw_relation_count": len(relations_raw),
    }

    if dropped_entities or dropped_relations:
        logger.warning(
            "Tolerant validation dropped entities=%d relations=%d reasons_entities=%s reasons_relations=%s",
            dropped_entities,
            dropped_relations,
            entity_drop_reasons[:3],
            relation_drop_reasons[:3],
        )

    if not entities:
        err = ValidationError.from_exception_data(
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
        # Attach diagnostics for callers that catch ValidationError.
        err._hsme_validation = {  # type: ignore[attr-defined]
            **validation_meta,
            "failure_class": "tolerant_drop_all",
        }
        raise err

    return {
        "entities": entities,
        "relations": relations,
        "_validation": {
            **validation_meta,
            "failure_class": None,
        },
    }


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


def validation_meta_from_error(exc: Exception) -> dict[str, Any]:
    """Best-effort diagnostics for extractor retry / final skip outcomes."""
    attached = getattr(exc, "_hsme_validation", None)
    if isinstance(attached, dict):
        return dict(attached)
    if isinstance(exc, ValidationError):
        msgs = [err.get("msg", "") for err in exc.errors()]
        if any("no valid entities remain" in str(m) for m in msgs):
            return {
                "failure_class": "tolerant_drop_all",
                "error_count": exc.error_count(),
                "error_messages": msgs[:5],
            }
        return {
            "failure_class": "schema_error",
            "error_count": exc.error_count(),
            "error_messages": msgs[:5],
        }
    return {
        "failure_class": "parse_error",
        "error_messages": [str(exc)[:200]],
    }
