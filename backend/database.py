import numpy as np
import re
from typing import List, Dict, Tuple, Optional
from backend.vsa import BipolarVSA
from backend.models import Entity, Experiment

class HSMEVectorDatabase:
    def __init__(self, dim: int = 10000):
        self.vsa = BipolarVSA(dim=dim, seed=42)
        # Maps entity_key (e.g. "Material:Никель") to its base VSA vector
        self.codebook: Dict[str, np.ndarray] = {}
        # Maps experiment_id to its raw Experiment object
        self.experiments: Dict[str, Experiment] = {}
        # Maps experiment_id to its encoded hypervector
        self.vector_store: Dict[str, np.ndarray] = {}
        
        # Pre-populate role vectors under the new mining-metallurgy ontology
        self.roles = ["Material", "Process", "Equipment", "Property", "Publication", "Expert", "Facility"]
        for role in self.roles:
            role_key = f"Role:{role}"
            self.codebook[role_key] = self.vsa.generate_vector()

    def get_or_create_vector(self, key: str) -> np.ndarray:
        """Retrieves an entity vector from the codebook, or generates a new one if not present."""
        if key not in self.codebook:
            self.codebook[key] = self.vsa.generate_vector()
        return self.codebook[key]

    def encode_experiment(self, experiment: Experiment) -> np.ndarray:
        """Encodes an experiment into a single VSA hypervector using the Role-Filler binding model."""
        bindings = []
        
        # Ingest all input, process, and output entities
        for entity in experiment.get_all_entities():
            role_vector = self.get_or_create_vector(f"Role:{entity.type}")
            filler_vector = self.get_or_create_vector(entity.to_key())
            
            # Bind role and filler
            bound = self.vsa.bind(role_vector, filler_vector)
            bindings.append(bound)
            
        if not bindings:
            return self.vsa.generate_vector()
            
        return self.vsa.bundle(bindings)

    def save_to_disk(self, filepath: str = "db_state.pkl"):
        """Saves the database state (codebook, experiments, vector_store) to a disk file."""
        import pickle
        state = {
            "codebook": self.codebook,
            "experiments": self.experiments,
            "vector_store": self.vector_store
        }
        with open(filepath, "wb") as f:
            pickle.dump(state, f)

    def load_from_disk(self, filepath: str = "db_state.pkl") -> bool:
        """Loads the database state from a disk file. Returns True if successful."""
        import pickle
        import os
        if not os.path.exists(filepath):
            return False
        try:
            with open(filepath, "rb") as f:
                state = pickle.load(f)
            self.codebook = state.get("codebook", {})
            self.experiments = state.get("experiments", {})
            self.vector_store = state.get("vector_store", {})
            return True
        except Exception as e:
            print(f"Error loading database from disk: {e}")
            return False

    def insert_experiment(self, experiment: Experiment):
        """Encodes and stores an experiment in the database and persists it to disk."""
        vector = self.encode_experiment(experiment)
        self.experiments[experiment.id] = experiment
        self.vector_store[experiment.id] = vector
        self.save_to_disk("db_state.pkl")

    def search(self, query_entities: List[Entity], limit: int = 5,
               year_start: Optional[int] = None, year_end: Optional[int] = None,
               geography: Optional[str] = None, source_type: Optional[str] = None) -> List[Tuple[Experiment, float]]:
        """Searches the database using VSA binding query, supporting relational metadata filters."""
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
            exp = self.experiments[exp_id]
            
            # Apply year filters
            if year_start is not None and exp.year is not None and exp.year < year_start:
                continue
            if year_end is not None and exp.year is not None and exp.year > year_end:
                continue
                
            # Apply geography filters
            if geography is not None and exp.geography is not None:
                if geography.lower() not in exp.geography.lower():
                    continue
                    
            # Apply source type filters
            if source_type is not None and exp.source_type is not None:
                if source_type.lower() != exp.source_type.lower():
                    continue
                    
            sim = self.vsa.similarity(query_vector, exp_vector)
            results.append((exp, sim))
            
        # Sort by similarity descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def get_counterfactuals(self, experiment_id: str) -> List[Dict]:
        """Finds experiments that differ from the target experiment by exactly one input parameter."""
        target = self.experiments.get(experiment_id)
        if not target:
            return []
            
        def get_output_map(entities):
            out_map = {}
            for e in entities:
                if e.type == "Property" and ":" in e.value:
                    name, val = e.value.split(":", 1)
                    out_map[name.strip()] = val.strip()
                else:
                    out_map[e.type] = e.value
            return out_map

        s1 = {e.to_key() for e in target.input_entities}
        target_outputs = get_output_map(target.output_entities)
        
        counterfactuals = []
        
        for exp_id, exp in self.experiments.items():
            if exp_id == experiment_id:
                continue
                
            s2 = {e.to_key() for e in exp.input_entities}
            
            # Counterfactual: same number of input entities, and exactly one entity differs
            if len(s1) == len(s2) and len(s1 & s2) == len(s1) - 1:
                diff_target = list(s1 - s2)[0]  # e.g. "Property:pH: 2.0"
                diff_exp = list(s2 - s1)[0]     # e.g. "Property:pH: 1.0"
                
                type_target, val_target = diff_target.split(":", 1)
                type_exp, val_exp = diff_exp.split(":", 1)
                
                # Check if the changed parameter has the same type
                if type_target == type_exp:
                    # Find output differences
                    exp_outputs = get_output_map(exp.output_entities)
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
                        "difference": {
                            "parameter": type_target,
                            "from": val_target,
                            "to": val_exp
                        },
                        "effects": output_diffs
                    })
                    
        return counterfactuals

    def analyze_gaps(self, dimensions: List[str]) -> List[Dict]:
        """Identifies gaps (missing configurations) across specified dimensions, predicting values from topological baselines."""
        # Collect all unique values for each dimension from experiment input entities
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
                
                # Predict any numeric property values dynamically
                predictions = []
                if similarities:
                    # Dynamically collect property types present in outputs of similar experiments
                    property_keys = set()
                    for exp, sim in similarities[:5]:
                        for out_entity in exp.output_entities:
                            if out_entity.type == "Property":
                                property_keys.add(out_entity.value)
                    
                    # Group property keys by type (e.g. "pH", "светлость") to aggregate numeric values
                    # If value contains digits, extract number and unit
                    numeric_aggregations = {}
                    for prop_val in property_keys:
                        # Extract first float or int
                        match = re.search(r'([-+]?\d*\.\d+|\b[-+]?\d+\b)', prop_val)
                        if match:
                            num = float(match.group(1))
                            unit = prop_val.replace(match.group(1), "").strip()
                            # Key by unit/labels to group similar metrics
                            clean_key = re.sub(r'[:=\d.,\s]+', ' ', unit).strip()
                            numeric_aggregations.setdefault(clean_key, []).append((num, unit))
                            
                    # Calculate weighted average for each aggregated property
                    for key, num_list in numeric_aggregations.items():
                        vals = []
                        weights = []
                        unit_label = num_list[0][1]
                        for val, unit in num_list:
                            # Find matching similar experiments
                            for exp, sim in similarities[:3]:
                                if sim > 0.05:
                                    for out_entity in exp.output_entities:
                                        if out_entity.type == "Property":
                                            m = re.search(r'([-+]?\d*\.\d+|\b[-+]?\d+\b)', out_entity.value)
                                            if m and abs(float(m.group(1)) - val) < 1e-6:
                                                vals.append(val)
                                                weights.append(sim)
                        if vals:
                            pred_val = np.average(vals, weights=weights)
                            # Format predicted value
                            # Try to preserve format (e.g. pH: value or value MPa)
                            predictions.append(Entity(type="Property", value=f"{unit_label} {pred_val:.1f}".strip()))
                
                gaps.append({
                    "configuration": combo_entities,
                    "similar_experiments": [s[0].id for s in similarities[:2] if s[1] > 0.05],
                    "predicted_properties": predictions
                })
                
        return gaps

def seed_database(db: HSMEVectorDatabase):
    """Seeds the database with high-quality mock research experiments in the mining-metallurgy domain."""
    mock_experiments = [
        # Series 1: Nickel Electrowinning (Электроэкстракция никеля)
        Experiment(
            id="EXP-NI-01",
            name="Никелевая электроэкстракция в хлоридном электролите при pH 2.0",
            input_entities=[
                Entity(type="Material", value="Хлоридный электролит никеля"),
                Entity(type="Property", value="pH: 2.0"),
                Entity(type="Property", value="плотность тока: 300 А/м2"),
                Entity(type="Facility", value="Кольская ГМК")
            ],
            process_entities=[
                Entity(type="Process", value="Электроэкстракция"),
                Entity(type="Equipment", value="Ванна электроэкстракции")
            ],
            output_entities=[
                Entity(type="Material", value="Никелевый катод"),
                Entity(type="Property", value="Светлость поверхности: 72 %"),
                Entity(type="Property", value="Выход по току: 94.5 %")
            ],
            evidence=["ОИП-09-2023"],
            confidence=0.95,
            year=2023,
            geography="RU",
            source_type="Обзор"
        ),
        Experiment(
            id="EXP-NI-02",
            name="Никелевая электроэкстракция в хлоридном электролите при pH 1.0 (Контрфакт)",
            input_entities=[
                Entity(type="Material", value="Хлоридный электролит никеля"),
                Entity(type="Property", value="pH: 1.0"),
                Entity(type="Property", value="плотность тока: 300 А/м2"),
                Entity(type="Facility", value="Кольская ГМК")
            ],
            process_entities=[
                Entity(type="Process", value="Электроэкстракция"),
                Entity(type="Equipment", value="Ванна электроэкстракции")
            ],
            output_entities=[
                Entity(type="Material", value="Никелевый катод"),
                Entity(type="Property", value="Светлость поверхности: 85 %"),
                Entity(type="Property", value="Выход по току: 89.2 %")
            ],
            evidence=["ОИП-09-2023"],
            confidence=0.90,
            year=2023,
            geography="RU",
            source_type="Обзор"
        ),
        Experiment(
            id="EXP-NI-03",
            name="Никелевая электроэкстракция в хлоридном электролите при высокой плотности тока",
            input_entities=[
                Entity(type="Material", value="Хлоридный электролит никеля"),
                Entity(type="Property", value="pH: 2.0"),
                Entity(type="Property", value="плотность тока: 500 А/м2"),
                Entity(type="Facility", value="Кольская ГМК")
            ],
            process_entities=[
                Entity(type="Process", value="Электроэкстракция"),
                Entity(type="Equipment", value="Ванна электроэкстракции")
            ],
            output_entities=[
                Entity(type="Material", value="Никелевый катод"),
                Entity(type="Property", value="Светлость поверхности: 51 %"),
                Entity(type="Property", value="Выход по току: 92.1 %")
            ],
            evidence=["ОИП-09-2023"],
            confidence=0.92,
            year=2023,
            geography="RU",
            source_type="Обзор"
        ),
        
        # Series 2: Copper Electrowinning (Электроэкстракция меди)
        Experiment(
            id="EXP-CU-01",
            name="Медная электроэкстракция из сернокислого раствора",
            input_entities=[
                Entity(type="Material", value="Сернокислый электролит меди"),
                Entity(type="Property", value="Температура: 45°C"),
                Entity(type="Property", value="плотность тока: 250 А/м2"),
                Entity(type="Facility", value="Завод Long Harbour")
            ],
            process_entities=[
                Entity(type="Process", value="Электроэкстракция"),
                Entity(type="Equipment", value="Ванна электроэкстракции")
            ],
            output_entities=[
                Entity(type="Material", value="Медный катод"),
                Entity(type="Property", value="Выход по току: 96.8 %")
            ],
            evidence=["ТИ-01-2017"],
            confidence=0.98,
            year=2017,
            geography="Global",
            source_type="Обзор"
        ),
        
        # Series 3: Heap Leaching in Cold Climates (Кучное выщелачивание)
        Experiment(
            id="EXP-HL-01",
            name="Кучное выщелачивание бедных медно-никелевых руд при температуре 5°C",
            input_entities=[
                Entity(type="Material", value="Бедная сульфидная медно-никелевая руда"),
                Entity(type="Property", value="Температура: 5°C"),
                Entity(type="Facility", value="рудник Кайерканский")
            ],
            process_entities=[
                Entity(type="Process", value="Кучное выщелачивание"),
                Entity(type="Equipment", value="Оросительные системы")
            ],
            output_entities=[
                Entity(type="Material", value="Продуктивный раствор Ni-Cu"),
                Entity(type="Property", value="Извлечение никеля: 62.4 %")
            ],
            evidence=["ТИ-05-2017"],
            confidence=0.88,
            year=2017,
            geography="RU",
            source_type="Обзор"
        ),
        Experiment(
            id="EXP-HL-02",
            name="Кучное выщелачивание бедных медно-никелевых руд при температуре 20°C (Теплый сезон)",
            input_entities=[
                Entity(type="Material", value="Бедная сульфидная медно-никелевая руда"),
                Entity(type="Property", value="Температура: 20°C"),
                Entity(type="Facility", value="рудник Кайерканский")
            ],
            process_entities=[
                Entity(type="Process", value="Кучное выщелачивание"),
                Entity(type="Equipment", value="Оросительные системы")
            ],
            output_entities=[
                Entity(type="Material", value="Продуктивный раствор Ni-Cu"),
                Entity(type="Property", value="Извлечение никеля: 74.1 %")
            ],
            evidence=["ТИ-05-2017"],
            confidence=0.90,
            year=2017,
            geography="RU",
            source_type="Обзор"
        )
    ]
    
    for exp in mock_experiments:
        db.insert_experiment(exp)
