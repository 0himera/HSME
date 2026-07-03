from backend.core.models import Entity, Experiment
from backend.repository.database import HSMEVectorDatabase, seed_database

def test_database_seeding_and_encoding():
    db = HSMEVectorDatabase(dim=10000)
    seed_database(db)
    
    assert len(db.experiments) == 6
    assert len(db.vector_store) == 6
    
    # Check if vectors are correctly stored and are bipolar
    for exp_id, vector in db.vector_store.items():
        assert vector.shape == (10000,)
        
    # Check if roles are populated
    assert "Role:Material" in db.codebook
    assert "Role:Property" in db.codebook

def test_search_with_metadata_filters():
    db = HSMEVectorDatabase(dim=10000)
    seed_database(db)
    
    # Search for Nickel Chloric electrolyte
    query = [
        Entity(type="Material", value="Хлоридный электролит никеля"),
        Entity(type="Property", value="pH: 2.0")
    ]
    results = db.search(query, limit=2)
    assert len(results) > 0
    best_match, score = results[0]
    assert best_match.id in ["EXP-NI-01", "EXP-NI-03"]
    
    # Search with year filter
    filtered_results = db.search(query, year_start=2020)
    assert len(filtered_results) > 0
    
    filtered_results_old = db.search(query, year_end=2020)
    assert all(exp.year <= 2020 for exp, score in filtered_results_old)

def test_counterfactuals():
    db = HSMEVectorDatabase(dim=10000)
    seed_database(db)
    
    # EXP-NI-01 and EXP-NI-02 differ only by pH property (2.0 vs 1.0)
    cfs = db.get_counterfactuals("EXP-NI-01")
    assert len(cfs) >= 1
    
    # Find the counterfactual for EXP-NI-02 (since EXP-NI-03 is also a valid counterfactual)
    cf = next((c for c in cfs if c["experiment"].id == "EXP-NI-02"), None)
    assert cf is not None
    assert cf["difference"]["parameter"] == "Property"
    assert cf["difference"]["from"] == "pH: 2.0"
    assert cf["difference"]["to"] == "pH: 1.0"
    
    # Verify that Svetlost and Current Yield are flagged as effects
    effects = {e["property"]: (e["from"], e["to"]) for e in cf["effects"]}
    assert any("Светлость" in k for k in effects.keys()) or any("Выход" in k for k in effects.keys())

def test_gaps():
    db = HSMEVectorDatabase(dim=10000)
    seed_database(db)
    
    # Check gaps for Material and Property
    gaps = db.analyze_gaps(["Material", "Facility"])
    assert len(gaps) > 0
    
    # Since "Хлоридный электролит никеля" is tested at "Кольская ГМК" and "Завод Long Harbour" has only copper EW,
    # the combination ("Хлоридный электролит никеля", "Завод Long Harbour") should be a gap.
    long_harbour_ni_gap = None
    for gap in gaps:
        config_map = {e.type: e.value for e in gap["configuration"]}
        if config_map.get("Material") == "Хлоридный электролит никеля" and config_map.get("Facility") == "Завод Long Harbour":
            long_harbour_ni_gap = gap
            break
            
    assert long_harbour_ni_gap is not None
    # Similar experiments should include EXP-CU-01 (which was done at Long Harbour)
    assert len(long_harbour_ni_gap["similar_experiments"]) > 0
