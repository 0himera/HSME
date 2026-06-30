from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import List, Dict, Any
import os

from backend.models import Entity, Experiment, SearchQuery, GapQuery
from backend.database import HSMEVectorDatabase, seed_database

app = FastAPI(title="HyperGraph Research Memory Engine")

# Enable CORS for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize and seed database
db = HSMEVectorDatabase(dim=10000)
seed_database(db)

@app.post("/api/ingest")
async def ingest_experiment(experiment: Experiment):
    """Ingests a new experiment, generates its VSA hypervector, and indexes it."""
    try:
        db.insert_experiment(experiment)
        return {"status": "success", "message": f"Experiment {experiment.id} ingested successfully."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/experiments", response_model=List[Experiment])
async def get_all_experiments():
    """Returns all stored experiments."""
    return list(db.experiments.values())

@app.post("/api/search")
async def search_experiments(query: SearchQuery):
    """Performs VSA semantic search using query entities."""
    try:
        results = db.search(query.entities, limit=query.limit)
        return [
            {
                "experiment": exp,
                "similarity": score
            }
            for exp, score in results
        ]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/counterfactuals/{experiment_id}")
async def get_counterfactuals(experiment_id: str):
    """Retrieves counterfactual experiments differing by exactly one parameter."""
    if experiment_id not in db.experiments:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return db.get_counterfactuals(experiment_id)

@app.get("/api/reason/{experiment_id}")
async def reason_causality(experiment_id: str):
    """Generates a causal explanation for an experiment based on counterfactual analysis."""
    if experiment_id not in db.experiments:
        raise HTTPException(status_code=404, detail="Experiment not found")
        
    exp = db.experiments[experiment_id]
    cfs = db.get_counterfactuals(experiment_id)
    
    if not cfs:
        return {
            "experiment_id": experiment_id,
            "has_explanation": False,
            "explanation": f"No direct counterfactuals found for {experiment_id} in the current database. Add experiments with similar inputs to unlock causal analysis."
        }
        
    explanations = []
    for cf in cfs:
        cf_exp = cf["experiment"]
        diff = cf["difference"]
        effects = cf["effects"]
        
        effect_strings = []
        for eff in effects:
            prop = eff["property"]
            v1 = eff["from"]
            v2 = eff["to"]
            
            # Try to calculate delta
            try:
                n1 = float(v1.split()[0])
                n2 = float(v2.split()[0])
                delta = n2 - n1
                sign = "+" if delta > 0 else ""
                unit = v1.split()[1] if len(v1.split()) > 1 else ""
                delta_str = f" ({sign}{delta:.1f} {unit})"
            except:
                delta_str = ""
                
            effect_strings.append(f"• property '{prop}' changed from {v1} to {v2}{delta_str}")
            
        eff_summary = "\n".join(effect_strings) if effect_strings else "• no significant properties changed."
        
        explanation = (
            f"Comparing {exp.id} ('{exp.name}') with {cf_exp.id} ('{cf_exp.name}'):\n"
            f"  - Parameter '{diff['parameter']}' was modified from {diff['from']} to {diff['to']}.\n"
            f"  - Observed causal effects:\n{eff_summary}\n"
        )
        explanations.append(explanation)
        
    full_explanation = (
        f"### Causal Reasoning Report for {exp.id}\n\n" +
        "\n".join(explanations) +
        f"**Conclusion**: Changing '{cfs[0]['difference']['parameter']}' indicates a direct causal influence on "
        f"'{cfs[0]['effects'][0]['property'] if cfs[0]['effects'] else 'output properties'}' with a confidence score of {exp.confidence:.2f}."
    )
    
    return {
        "experiment_id": experiment_id,
        "has_explanation": True,
        "explanation": full_explanation
    }

@app.post("/api/gaps")
async def find_gaps(query: GapQuery):
    """Analyzes missing combinations (gaps) in research dimensions."""
    try:
        gaps = db.analyze_gaps(query.dimensions)
        return gaps
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/enrich-gap")
async def enrich_gap(gap_config: List[Entity]):
    """Extrapolates property values and generates a hypothesis for a missing configuration."""
    config_desc = ", ".join([f"{e.type}: {e.value}" for e in gap_config])
    
    # Try to find similarity-based prediction
    dimensions = [e.type for e in gap_config]
    all_gaps = db.analyze_gaps(dimensions)
    
    matching_gap = None
    for gap in all_gaps:
        gap_map = {e.type: e.value for e in gap["configuration"]}
        if all(gap_map.get(e.type) == e.value for e in gap_config):
            matching_gap = gap
            break
            
    if not matching_gap:
        return {
            "configuration": gap_config,
            "hypothesis": f"Configuration [{config_desc}] is either not a gap (already exists) or could not be mapped. Please verify dimensions."
        }
        
    predicted_props = matching_gap["predicted_properties"]
    prop_desc = ", ".join([f"{p.type} ~ {p.value}" for p in predicted_props]) if predicted_props else "Unknown properties"
    
    # Generate hypothesis text
    similar_ids = matching_gap["similar_experiments"]
    sim_details = []
    for sid in similar_ids:
        sexp = db.experiments[sid]
        inputs = ", ".join([f"{e.value}" for e in sexp.input_entities if e.type in dimensions])
        outputs = ", ".join([f"{e.type}={e.value}" for e in sexp.output_entities])
        sim_details.append(f"  * {sexp.id} ({inputs}) -> {outputs}")
        
    sim_context = "\n".join(sim_details) if sim_details else "  * No closely matching baseline experiments found."
    
    hypothesis = (
        f"### Research Hypothesis for: [{config_desc}]\n\n"
        f"**Extrapolated Properties**:\n- {prop_desc}\n\n"
        f"**Rationale & Topologiocal Baselines**:\n"
        f"We identified existing nearby experiments in the hypergraph mapping:\n{sim_context}\n\n"
        f"By calculating the hypervector topological trends across the matching dimensions, "
        f"the engine predicts that this configuration lies on the stable response manifold. "
        f"We recommend conducting a physical experiment at these coordinates to confirm this manifold boundary."
    )
    
    return {
        "configuration": gap_config,
        "predicted_properties": predicted_props,
        "hypothesis": hypothesis
    }

# Mount static frontend files if directory exists
frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
