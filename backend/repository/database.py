import numpy as np
import re
from typing import List, Dict, Tuple, Optional, Any
from backend.core.vsa import BipolarVSA
from backend.core.models import Entity, Experiment

class HSMEVectorDatabase:
    def __init__(self, dim: int = 10000):
        self.vsa = BipolarVSA(dim=dim, seed=42)
        # Maps entity_key (e.g. "Material:Никель") to its base VSA vector
        self.codebook: Dict[str, np.ndarray] = {}
        # Maps experiment_id to its raw Experiment object
        self.experiments: Dict[str, Experiment] = {}
        # Maps experiment_id to its encoded hypervector
        self.vector_store: Dict[str, np.ndarray] = {}
        # List of AuditEntry
        self.audit_logs: List[Any] = []
        # Database filepath for persistence
        import os
        self.db_filepath = os.environ.get("HSME_DATABASE_FILE", ".local/db_state.pkl")
        import threading
        self._write_lock = threading.Lock()
        
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

    def get_entity_by_value(self, experiment: Experiment, value: str) -> Optional[Entity]:
        """Finds an entity within an experiment by its value (case-insensitive)."""
        val_lower = value.strip().lower()
        for e in experiment.get_all_entities():
            if e.value.strip().lower() == val_lower:
                return e
        return None

    def parse_numeric_property(self, value_str: str) -> Optional[Tuple[str, str, float, str]]:
        """Parses a property value string.
        Returns Tuple of (name, operator, float_value, unit) if matched, else None.
        """
        # Match e.g. "pH: 2.0", "pH = 2.5", "плотность тока: 300 А/м2", "pH < 2.0", "Температура: 45°C"
        pattern = r'^([^0-9:=<>≤≥\s]+)\s*[:=]?\s*([<>≤≥=]|<=|>=)?\s*([-+]?\d*(?:[.,]\d+)?)\s*(.*)$'
        match = re.match(pattern, value_str.strip())
        if match:
            name, op, val_str, unit = match.groups()
            try:
                val = float(val_str.replace(',', '.'))
                return name.strip(), op or "", val, unit.strip()
            except ValueError:
                return None
        return None

    def get_property_range(self, name: str, unit: str) -> Tuple[float, float]:
        """Returns standard or dynamic range for a property name."""
        name_lower = name.lower()
        if "ph" in name_lower:
            return (0.0, 14.0)
        elif "температура" in name_lower or "temp" in name_lower:
            return (0.0, 1200.0)
        elif "плотность" in name_lower or "density" in name_lower:
            return (0.0, 1000.0)
        elif "%" in unit or "выход" in name_lower or "извлечение" in name_lower or "светлость" in name_lower:
            return (0.0, 100.0)
        return (0.0, 1000.0)

    def get_entity_vector(self, entity: Entity) -> np.ndarray:
        """Computes the hypervector for an entity. Handles numeric properties with interpolation."""
        if entity.type == "Property":
            parsed = self.parse_numeric_property(entity.value)
            if parsed:
                name, op, val, unit = parsed
                r_min, r_max = self.get_property_range(name, unit)
                
                # Determine query value based on operator
                if op in ["<", "≤"]:
                    val = (r_min + val) / 2.0
                elif op in [">", "≥"]:
                    val = (val + r_max) / 2.0
                
                # Interpolate
                p = (val - r_min) / (r_max - r_min) if r_max > r_min else 0.0
                p = max(0.0, min(1.0, p))
                
                v_min = self.get_or_create_vector(f"NumericBase:{name.lower()}:min")
                v_max = self.get_or_create_vector(f"NumericBase:{name.lower()}:max")
                
                N = int(p * self.vsa.dim)
                v_x = np.empty_like(v_min)
                v_x[:N] = v_max[:N]
                v_x[N:] = v_min[N:]
                return v_x

        return self.get_or_create_vector(entity.to_key())

    def encode_experiment(self, experiment: Experiment) -> np.ndarray:
        """Encodes an experiment into a single VSA hypervector using the Role-Filler binding model and relation Permutation."""
        bindings = []
        
        # Ingest all input, process, and output entities
        for entity in experiment.get_all_entities():
            role_vector = self.get_or_create_vector(f"Role:{entity.type}")
            filler_vector = self.get_entity_vector(entity)
            
            # Bind role and filler
            bound = self.vsa.bind(role_vector, filler_vector)
            bindings.append(bound)
            
        # Ingest all relations
        for relation in getattr(experiment, "relations", []):
            source_ent = self.get_entity_by_value(experiment, relation.source)
            target_ent = self.get_entity_by_value(experiment, relation.target)
            
            if source_ent and target_ent:
                v_source = self.get_entity_vector(source_ent)
                v_target = self.get_entity_vector(target_ent)
                v_relation_type = self.get_or_create_vector(f"RelationType:{relation.type}")
                
                # V_relation = Permute(V_source) * V_relation_type * V_target
                bound_rel = self.vsa.bind(
                    self.vsa.bind(self.vsa.permute(v_source, 1), v_relation_type),
                    v_target
                )
                bindings.append(bound_rel)

        if not bindings:
            return self.vsa.generate_vector()
            
        return self.vsa.bundle(bindings)

    def save_to_disk(self, filepath: str = None, run_in_background: bool = False):
        """Saves the database state (codebook, experiments, vector_store, audit_logs) to a disk file."""
        if filepath is None:
            filepath = self.db_filepath
        
        import pickle
        
        # Shallow copy dictionaries in the main thread to ensure thread safety
        # before pickling in the background thread.
        codebook_copy = dict(self.codebook)
        experiments_copy = dict(self.experiments)
        vector_store_copy = dict(self.vector_store)
        audit_logs_copy = list(self.audit_logs)
        
        def _write_to_disk():
            state = {
                "codebook": codebook_copy,
                "experiments": experiments_copy,
                "vector_store": vector_store_copy,
                "audit_logs": audit_logs_copy
            }
            try:
                with self._write_lock:
                    dirpath = os.path.dirname(filepath)
                    if dirpath:
                        os.makedirs(dirpath, exist_ok=True)
                    with open(filepath, "wb") as f:
                        pickle.dump(state, f)
            except Exception as e:
                print(f"Error saving database to disk: {e}")
                
        if run_in_background:
            import threading
            threading.Thread(target=_write_to_disk, daemon=True).start()
        else:
            _write_to_disk()

    def load_from_disk(self, filepath: str = None) -> bool:
        """Loads the database state from a disk file. Returns True if successful."""
        if filepath is None:
            filepath = self.db_filepath
        import pickle
        import os
        import json
        from backend.core.models import AuditEntry
        
        if not os.path.exists(filepath):
            return False
        try:
            with open(filepath, "rb") as f:
                state = pickle.load(f)
            self.codebook = state.get("codebook", {})
            self.experiments = state.get("experiments", {})
            self.vector_store = state.get("vector_store", {})
            self.audit_logs = state.get("audit_logs", [])
            
            # Load additional logs from audit_logs.jsonl if they exist
            audit_path = os.path.join(os.path.dirname(filepath), "audit_logs.jsonl") if os.path.dirname(filepath) else "audit_logs.jsonl"
            if os.path.exists(audit_path):
                try:
                    with open(audit_path, "r", encoding="utf-8") as f_audit:
                        for line in f_audit:
                            line = line.strip()
                            if line:
                                data = json.loads(line)
                                entry = AuditEntry(**data)
                                # Avoid duplicating entries already loaded from pickle if any
                                if not any(existing.timestamp == entry.timestamp and existing.action == entry.action for existing in self.audit_logs):
                                    self.audit_logs.append(entry)
                except Exception as audit_err:
                    print(f"Error loading audit logs from {audit_path}: {audit_err}")
            
            # Seed the audit_logs.jsonl file if we loaded historical logs from pickle but the JSONL file doesn't exist
            if self.audit_logs and not os.path.exists(audit_path):
                try:
                    with open(audit_path, "w", encoding="utf-8") as f_audit:
                        for entry in self.audit_logs:
                            f_audit.write(entry.model_dump_json() + "\n")
                except Exception as write_err:
                    print(f"Error seeding initial audit logs: {write_err}")
                    
            return True
        except Exception as e:
            print(f"Error loading database from disk: {e}")
            return False

    def insert_experiment(self, experiment: Experiment, auto_save: bool = True):
        """Encodes and stores an experiment in the database and persists it to disk in background."""
        vector = self.encode_experiment(experiment)
        self.experiments[experiment.id] = experiment
        self.vector_store[experiment.id] = vector
        if auto_save:
            self.save_to_disk(self.db_filepath, run_in_background=True)

    def log_action(self, username: str, role: str, action: str, details: str):
        """Logs an action and appends it to a separate log file, bypassing database serialization."""
        from datetime import datetime
        from backend.core.models import AuditEntry
        import os
        now = datetime.now().isoformat()
        entry = AuditEntry(
            timestamp=now,
            username=username,
            role=role,
            action=action,
            details=details
        )
        self.audit_logs.append(entry)
        
        # Append to a separate JSON lines file. This is an O(1) operation
        # that takes less than a millisecond, preventing Event Loop blocking.
        audit_path = os.path.join(os.path.dirname(self.db_filepath), "audit_logs.jsonl") if os.path.dirname(self.db_filepath) else "audit_logs.jsonl"
        try:
            with open(audit_path, "a", encoding="utf-8") as f:
                f.write(entry.model_dump_json() + "\n")
        except Exception as e:
            print(f"Error writing audit log entry: {e}")

    def search(self, query_entities: List[Entity], limit: int = 5,
               year_start: Optional[int] = None, year_end: Optional[int] = None,
               geography: Optional[str] = None, source_type: Optional[str] = None,
               exclude_sensitive: bool = False) -> List[Tuple[Experiment, float]]:
        """Searches the database using VSA binding query, supporting relational metadata filters."""
        if not query_entities:
            return []
            
        bindings = []
        for entity in query_entities:
            role_vector = self.get_or_create_vector(f"Role:{entity.type}")
            filler_vector = self.get_entity_vector(entity)
            bindings.append(self.vsa.bind(role_vector, filler_vector))
            
        query_vector = self.vsa.bundle(bindings)
        
        results = []
        for exp_id, exp_vector in self.vector_store.items():
            exp = self.experiments[exp_id]
            
            # Apply sensitivity filter
            if exclude_sensitive and exp.is_sensitive:
                continue
                
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

    def analyze_gaps(self, dimensions: List[str], min_experiments: int = 3, specific_combinations: Optional[List[List[Entity]]] = None) -> List[Dict]:
        """Identifies gaps (missing or poorly studied configurations) across specified dimensions.
           Also flags configurations that exist only in domestic or only in foreign literature."""
        
        # Build a map of combinations -> experiments and count value frequencies
        from collections import defaultdict, Counter
        import itertools
        
        combo_to_exps = defaultdict(list)
        value_counts = defaultdict(Counter)
        
        for exp in self.experiments.values():
            exp_conds = defaultdict(list)
            for e in exp.input_entities + exp.process_entities:
                if not specific_combinations or e.type in dimensions:
                    exp_conds[e.type].append(e.value)
                    value_counts[e.type][e.value] += 1
            
            # If the experiment has all required dimensions
            if all(dim in exp_conds for dim in dimensions):
                sub_combos = list(itertools.product(*[exp_conds[d] for d in dimensions]))
                for sc in sub_combos:
                    combo_to_exps[sc].append(exp)

        if specific_combinations:
            combinations = [tuple(e.value for e in combo) for combo in specific_combinations]
        else:
            # Determine limit per dimension to keep cartesian product size reasonable (e.g. max ~10,000 combinations)
            num_dims = len(dimensions)
            if num_dims == 1:
                limit = 500
            elif num_dims == 2:
                limit = 100
            elif num_dims == 3:
                limit = 20
            else:
                limit = 10
                
            sorted_values = {}
            for d in dimensions:
                # Use only the most common values to avoid cartesian product explosion
                most_common = [val for val, count in value_counts[d].most_common(limit)]
                sorted_values[d] = sorted(most_common)
                
            if not all(sorted_values[d] for d in dimensions):
                return []
                
            combinations = list(itertools.product(*[sorted_values[d] for d in dimensions]))

        gaps = []
        for combo in combinations:
            exps_for_combo = combo_to_exps.get(combo, [])
            count = len(exps_for_combo)
            
            gap_type = None
            if count == 0:
                gap_type = "missing"
            elif count < min_experiments:
                gap_type = "weak"
            else:
                domestic_count = sum(1 for e in exps_for_combo if e.geography and any(ru in e.geography.lower() for ru in ["росси", "рф", "domestic", "ссср"]))
                foreign_count = count - domestic_count
                
                if domestic_count == 0 and foreign_count > 0:
                    gap_type = "foreign_only"
                elif foreign_count == 0 and domestic_count > 0:
                    gap_type = "domestic_only"
                    
            if not gap_type:
                continue

            gaps.append((combo, gap_type, count))
            
        # Sort gaps to prioritize interesting gaps (weak, domestic_only, foreign_only) over completely missing ones
        def gap_priority(g):
            ptype = g[1]
            if ptype in ["domestic_only", "foreign_only"]: return 0
            if ptype == "weak": return 1
            return 2
            
        gaps.sort(key=gap_priority)
        
        # Only compute heavy VSA similarities and predictions for the top 100 prioritized gaps
        limited_gaps = gaps[:100]
        result_gaps = []
        
        for combo, gap_type, count in limited_gaps:
            combo_entities = [Entity(type=dimensions[i], value=combo[i]) for i in range(len(dimensions))]
            query_bindings = []
            for entity in combo_entities:
                role_vector = self.get_or_create_vector(f"Role:{entity.type}")
                filler_vector = self.get_or_create_vector(entity.to_key())
                query_bindings.append(self.vsa.bind(role_vector, filler_vector))
            query_vector = self.vsa.bundle(query_bindings)
            
            similarities = []
            for exp_id, exp_vector in self.vector_store.items():
                sim = self.vsa.similarity(query_vector, exp_vector)
                similarities.append((self.experiments[exp_id], sim))
            similarities.sort(key=lambda x: x[1], reverse=True)
            
            predictions = []
            if similarities:
                property_keys = set()
                for exp, sim in similarities[:5]:
                    for out_entity in exp.output_entities:
                        if out_entity.type == "Property":
                            property_keys.add(out_entity.value)
                
                numeric_aggregations = {}
                for prop_val in property_keys:
                    match = re.search(r'([-+]?\d*\.\d+|\b[-+]?\d+\b)', prop_val)
                    if match:
                        num = float(match.group(1))
                        unit = prop_val.replace(match.group(1), "").strip()
                        clean_key = re.sub(r'[:=\d.,\s]+', ' ', unit).strip()
                        numeric_aggregations.setdefault(clean_key, []).append((num, unit))
                        
                for key, num_list in numeric_aggregations.items():
                    vals = []
                    weights = []
                    unit_label = num_list[0][1]
                    for val, unit in num_list:
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
                        predictions.append(Entity(type="Property", value=f"{unit_label} {pred_val:.1f}".strip()))
            
            result_gaps.append({
                "configuration": combo_entities,
                "gap_type": gap_type,
                "experiment_count": count,
                "similar_experiments": [s[0].id for s in similarities[:2] if s[1] > 0.05],
                "predicted_properties": predictions
            })
            
        return result_gaps

from backend.repository.seeding import seed_database

# Instantiate the global database and load/seed it
db = HSMEVectorDatabase(dim=10000)
if not db.load_from_disk(db.db_filepath) or not any(exp.is_sensitive for exp in db.experiments.values() if exp.id.startswith("EXP-NI")) or not any(getattr(exp, "relations", None) for exp in db.experiments.values()):
    print(f"No persisted database found, old data format, or missing relations. Seeding mock experiments to {db.db_filepath}...")
    db.experiments.clear()
    db.vector_store.clear()
    seed_database(db)
    db.save_to_disk(db.db_filepath)
else:
    print(f"Loaded database state successfully from disk ({db.db_filepath}).")
