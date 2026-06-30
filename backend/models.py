from pydantic import BaseModel, Field
from typing import List, Optional

class Entity(BaseModel):
    type: str  # e.g., "Alloy", "Temperature", "Cooling", "Yield Strength"
    value: str  # e.g., "Alloy X", "900°C", "Oil Cooling", "620 MPa"

    def to_key(self) -> str:
        """Returns a string representation to map to the VSA codebook."""
        return f"{self.type}:{self.value}"

class Experiment(BaseModel):
    id: str
    name: str
    input_entities: List[Entity] = Field(default_factory=list)
    process_entities: List[Entity] = Field(default_factory=list)
    output_entities: List[Entity] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    def get_all_entities(self) -> List[Entity]:
        """Flatten all entities inside this experiment."""
        return self.input_entities + self.process_entities + self.output_entities

class SearchQuery(BaseModel):
    entities: List[Entity]
    limit: int = 5

class GapQuery(BaseModel):
    dimensions: List[str] = Field(..., description="Entity types to check coverage for (e.g. ['Alloy', 'Temperature', 'Cooling'])")
