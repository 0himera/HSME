import numpy as np
from typing import List, Dict, Tuple, Optional
from backend.vsa import BipolarVSA
from backend.models import Entity, Experiment

class HSMEVectorDatabase:
    def __init__(self, dim: int = 10000):
        self.vsa = BipolarVSA(dim=dim, seed=42)
        # Maps entity_key (e.g. "Alloy:Alloy A") to its base VSA vector
        self.codebook: Dict[str, np.ndarray] = {}
        # Maps experiment_id to its raw Experiment object
        self.experiments: Dict[str, Experiment] = {}
        # Maps experiment_id to its encoded hypervector
        self.vector_store: Dict[str, np.ndarray] = {}
        
        # Pre-populate role vectors
        self.roles = ["Alloy", "Temperature", "Cooling", "Pressure", "Yield Strength", "Hardness", "Heat Treatment"]
        for role in self.roles:
            role_key = f"Role:{role}"
            self.codebook[role_key] = self.vsa.generate_vector()

    def get_or_create_vector(self, key: str) -> np.ndarray:
        """Retrieves an entity vector from the codebook, or generates a new one if not present."""
        if key not in self.codebook:
            self.codebook[key] = self.vsa.generate_vector()
        return self.codebook[key]

    def encode_experiment(self, experiment: Experiment) -> np.ndarray:
        """Encodes an experiment into a single VSA hypervector.
        
        We use the Role-Filler binding model:
        V_exp = bundle( bind(Role_1, Filler_1), bind(Role_2, Filler_2), ... )
        """
        bindings = []
        
        # Ingest all input, process, and output entities
        for entity in experiment.get_all_entities():
            role_vector = self.get_or_create_vector(f"Role:{entity.type}")
            filler_vector = self.get_or_create_vector(entity.to_key())
            
            # Bind role and filler
            bound = self.vsa.bind(role_vector, filler_vector)
            bindings.append(bound)
            
        if not bindings:
            # Fallback to random vector if experiment has no entities
            return self.vsa.generate_vector()
            
        # Bundle all bindings together
        return self.vsa.bundle(bindings)

    def insert_experiment(self, experiment: Experiment):
        """Encodes and stores an experiment in the in-memory database."""
        vector = self.encode_experiment(experiment)
        self.experiments[experiment.id] = experiment
        self.vector_store[experiment.id] = vector

    def search(self, query_entities: List[Entity], limit: int = 5) -> List[Tuple[Experiment, float]]:
        """Searches the database using a VSA query.
        
        We construct a query vector by bundling the bound role-fillers of the query entities:
        V_query = bundle( bind(Role_i, Filler_i) )
        Then, we compute cosine similarity against all stored experiment vectors.
        """
        if not query_entities:
            return []
            
        bindings = []
        for entity in query_entities:
            role_vector = self.get_or_create_vector(f"Role:{entity.type}")
            filler_vector = self.get_or_create_vector(entity.to_key())
            bindings.append(self.vsa.bind(role_vector, filler_vector))
            
        query_vector = self.vsa.bundle(bindings)
        
        results = []
        for exp_id, exp_vector in self.vector_store.items():
            sim = self.vsa.similarity(query_vector, exp_vector)
            results.append((self.experiments[exp_id], sim))
            
        # Sort by similarity descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def get_counterfactuals(self, experiment_id: str) -> List[Dict]:
        """Finds experiments that differ from the target experiment by exactly one input parameter.
        
        This reveals the causal effect of changing that specific parameter on the outputs.
        """
        target = self.experiments.get(experiment_id)
        if not target:
            return []
            
        target_inputs = {e.type: e.value for e in target.input_entities}
        target_outputs = {e.type: e.value for e in target.output_entities}
        
        counterfactuals = []
        
        for exp_id, exp in self.experiments.items():
            if exp_id == experiment_id:
                continue
                
            exp_inputs = {e.type: e.value for e in exp.input_entities}
            exp_outputs = {e.type: e.value for e in exp.output_entities}
            
            # Find input mismatches
            all_input_keys = set(target_inputs.keys()) | set(exp_inputs.keys())
            input_diffs = []
            
            for key in all_input_keys:
                val1 = target_inputs.get(key)
                val2 = exp_inputs.get(key)
                if val1 != val2:
                    input_diffs.append({
                        "parameter": key,
                        "from": val1,
                        "to": val2
                    })
            
            # Counterfactual: exactly one input parameter differs
            if len(input_diffs) == 1:
                # Find output differences
                all_output_keys = set(target_outputs.keys()) | set(exp_outputs.keys())
                output_diffs = []
                for key in all_output_keys:
                    val1 = target_outputs.get(key)
                    val2 = exp_outputs.get(key)
                    if val1 != val2:
                        output_diffs.append({
                            "property": key,
                            "from": val1,
                            "to": val2
                        })
                        
                counterfactuals.append({
                    "experiment": exp,
                    "difference": input_diffs[0],
                    "effects": output_diffs
                })
                
        return counterfactuals

    def analyze_gaps(self, dimensions: List[str]) -> List[Dict]:
        """Identifies gaps (missing configurations) across specified dimensions (e.g. Alloy, Temperature).
        
        We form a grid (Cartesian product) of all existing values for these dimensions,
        find which combinations do not exist in the database, and estimate their properties/interest.
        """
        # Collect all unique values for each dimension
        values_per_dim = {}
        for dim in dimensions:
            vals = set()
            for exp in self.experiments.values():
                for entity in exp.input_entities:
                    if entity.type == dim:
                        vals.add(entity.value)
            values_per_dim[dim] = sorted(list(vals))
            
        if not all(values_per_dim.values()):
            return []
            
        # Generate all combinations (Cartesian product)
        import itertools
        combinations = list(itertools.product(*[values_per_dim[d] for d in dimensions]))
        
        gaps = []
        for combo in combinations:
            # Map combo back to entities
            combo_entities = [Entity(type=dimensions[i], value=combo[i]) for i in range(len(dimensions))]
            
            # Check if this combination exists in any experiment inputs
            exists = False
            for exp in self.experiments.values():
                exp_inputs = {e.type: e.value for e in exp.input_entities}
                if all(exp_inputs.get(dimensions[i]) == combo[i] for i in range(len(dimensions))):
                    exists = True
                    break
                    
            if not exists:
                # Predict property based on VSA similarity
                # Query vector for the missing inputs
                query_bindings = []
                for entity in combo_entities:
                    role_vector = self.get_or_create_vector(f"Role:{entity.type}")
                    filler_vector = self.get_or_create_vector(entity.to_key())
                    query_bindings.append(self.vsa.bind(role_vector, filler_vector))
                query_vector = self.vsa.bundle(query_bindings)
                
                # Find most similar existing experiments
                similarities = []
                for exp_id, exp_vector in self.vector_store.items():
                    sim = self.vsa.similarity(query_vector, exp_vector)
                    similarities.append((self.experiments[exp_id], sim))
                similarities.sort(key=lambda x: x[1], reverse=True)
                
                # Predict value from top matches
                predictions = []
                if similarities:
                    # Find output property values in similar experiments (e.g. Yield Strength)
                    for output_type in ["Yield Strength", "Hardness"]:
                        vals = []
                        weights = []
                        for exp, sim in similarities[:3]:
                            if sim > 0.1:  # Only count relevant matches
                                for out_entity in exp.output_entities:
                                    if out_entity.type == output_type:
                                        # Extract numeric value if possible
                                        try:
                                            num_val = float(out_entity.value.split()[0])
                                            vals.append(num_val)
                                            weights.append(sim)
                                        except:
                                            pass
                        if vals:
                            # Weighted average prediction
                            pred_val = np.average(vals, weights=weights)
                            unit = "MPa" if output_type == "Yield Strength" else ""
                            predictions.append(Entity(type=output_type, value=f"{pred_val:.1f} {unit}".strip()))
                
                gaps.append({
                    "configuration": combo_entities,
                    "similar_experiments": [s[0].id for s in similarities[:2] if s[1] > 0.1],
                    "predicted_properties": predictions
                })
                
        return gaps

def seed_database(db: HSMEVectorDatabase):
    """Seeds the database with high-quality mock research experiments."""
    mock_experiments = [
        # Alloy A series
        Experiment(
            id="EXP-A01",
            name="Alloy A Annealing at 900°C",
            input_entities=[
                Entity(type="Alloy", value="Alloy A"),
                Entity(type="Temperature", value="900°C"),
                Entity(type="Cooling", value="Oil Cooling"),
                Entity(type="Pressure", value="1 atm")
            ],
            process_entities=[Entity(type="Heat Treatment", value="Annealing")],
            output_entities=[
                Entity(type="Yield Strength", value="620 MPa"),
                Entity(type="Hardness", value="190 HB")
            ],
            evidence=["study_alloy_a_v1.pdf", "lab_notes_2026_05.txt"],
            confidence=0.95
        ),
        Experiment(
            id="EXP-A02",
            name="Alloy A Annealing at 950°C",
            input_entities=[
                Entity(type="Alloy", value="Alloy A"),
                Entity(type="Temperature", value="950°C"),
                Entity(type="Cooling", value="Oil Cooling"),
                Entity(type="Pressure", value="1 atm")
            ],
            process_entities=[Entity(type="Heat Treatment", value="Annealing")],
            output_entities=[
                Entity(type="Yield Strength", value="690 MPa"),
                Entity(type="Hardness", value="210 HB")
            ],
            evidence=["study_alloy_a_v1.pdf"],
            confidence=0.90
        ),
        
        # Alloy B series
        Experiment(
            id="EXP-B01",
            name="Alloy B Heat Treatment at 900°C",
            input_entities=[
                Entity(type="Alloy", value="Alloy B"),
                Entity(type="Temperature", value="900°C"),
                Entity(type="Cooling", value="Oil Cooling"),
                Entity(type="Pressure", value="1 atm")
            ],
            process_entities=[Entity(type="Heat Treatment", value="Annealing")],
            output_entities=[
                Entity(type="Yield Strength", value="580 MPa"),
                Entity(type="Hardness", value="175 HB")
            ],
            evidence=["project_b_summary.docx"],
            confidence=0.85
        ),
        Experiment(
            id="EXP-B02",
            name="Alloy B Heat Treatment at 950°C",
            input_entities=[
                Entity(type="Alloy", value="Alloy B"),
                Entity(type="Temperature", value="950°C"),
                Entity(type="Cooling", value="Oil Cooling"),
                Entity(type="Pressure", value="1 atm")
            ],
            process_entities=[Entity(type="Heat Treatment", value="Annealing")],
            output_entities=[
                Entity(type="Yield Strength", value="640 MPa"),
                Entity(type="Hardness", value="195 HB")
            ],
            evidence=["project_b_summary.docx"],
            confidence=0.88
        ),
        Experiment(
            id="EXP-B03",
            name="Alloy B Heat Treatment at 1000°C",
            input_entities=[
                Entity(type="Alloy", value="Alloy B"),
                Entity(type="Temperature", value="1000°C"),
                Entity(type="Cooling", value="Oil Cooling"),
                Entity(type="Pressure", value="1 atm")
            ],
            process_entities=[Entity(type="Heat Treatment", value="Annealing")],
            output_entities=[
                Entity(type="Yield Strength", value="710 MPa"),
                Entity(type="Hardness", value="220 HB")
            ],
            evidence=["project_b_summary.docx", "high_temp_safety.pdf"],
            confidence=0.92
        ),
        
        # Alloy C Series (Water Cooling to show differences)
        Experiment(
            id="EXP-C01",
            name="Alloy C Hardening via Water Cooling",
            input_entities=[
                Entity(type="Alloy", value="Alloy C"),
                Entity(type="Temperature", value="900°C"),
                Entity(type="Cooling", value="Water Cooling"),
                Entity(type="Pressure", value="1 atm")
            ],
            process_entities=[Entity(type="Heat Treatment", value="Quenching")],
            output_entities=[
                Entity(type="Yield Strength", value="750 MPa"),
                Entity(type="Hardness", value="240 HB")
            ],
            evidence=["quenching_methods_v2.pdf"],
            confidence=0.90
        ),
        Experiment(
            id="EXP-C02",
            name="Alloy C Hardening via Air Cooling (Control)",
            input_entities=[
                Entity(type="Alloy", value="Alloy C"),
                Entity(type="Temperature", value="900°C"),
                Entity(type="Cooling", value="Air Cooling"),
                Entity(type="Pressure", value="1 atm")
            ],
            process_entities=[Entity(type="Heat Treatment", value="Quenching")],
            output_entities=[
                Entity(type="Yield Strength", value="510 MPa"),
                Entity(type="Hardness", value="160 HB")
            ],
            evidence=["quenching_methods_v2.pdf"],
            confidence=0.95
        )
    ]
    for exp in mock_experiments:
        db.insert_experiment(exp)
