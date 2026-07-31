from pydantic import BaseModel, Field
from typing import List, Optional

from backend.services.embedding import normalize_entity_key

class Entity(BaseModel):
    type: str  # e.g., "Material", "Process", "Equipment", "Property", "Expert", "Publication", "Facility"
    value: str  # e.g., "Nickel", "Electrowinning", "EW Bath", "pH: 2", "Evgrafova A.K.", "TI-05-2017", "Gipronickel"

    def to_key(self) -> str:
        """Returns a string representation to map to the VSA codebook."""
        return normalize_entity_key(f"{self.type}:{self.value}")

class Relation(BaseModel):
    source: str
    type: str
    target: str

class Experiment(BaseModel):
    id: str
    name: str
    input_entities: List[Entity] = Field(default_factory=list)
    process_entities: List[Entity] = Field(default_factory=list)
    output_entities: List[Entity] = Field(default_factory=list)
    relations: List[Relation] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    
    # Metadata fields for rich filtering
    year: Optional[int] = None
    geography: Optional[str] = "Global"  # e.g. "RU", "Global", "Australia", "New Caledonia"
    source_type: Optional[str] = None    # e.g. "Обзор", "Статья", "Доклад"
    is_sensitive: bool = False

    def get_all_entities(self) -> List[Entity]:
        """Flatten all entities inside this experiment."""
        return self.input_entities + self.process_entities + self.output_entities

class SearchQuery(BaseModel):
    entities: Optional[List[Entity]] = None
    query: Optional[str] = None
    limit: int = 5
    skip: int = 0
    paged: bool = False
    # Optional metadata filters
    year_start: Optional[int] = None
    year_end: Optional[int] = None
    geography: Optional[str] = None
    source_type: Optional[str] = None

class GapQuery(BaseModel):
    dimensions: List[str] = Field(..., description="Entity types to check coverage for (e.g. ['Material', 'Process', 'Equipment'])")
    min_experiments: int = Field(default=3, description="Threshold for poorly studied combinations")

class AuditEntry(BaseModel):
    timestamp: str
    username: str
    role: str
    action: str
    details: str
