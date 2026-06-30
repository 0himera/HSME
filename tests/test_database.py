import pytest
from backend.models import Entity, Experiment
from backend.database import HSMEVectorDatabase, seed_database

def test_database_seeding_and_encoding():
    db = HSMEVectorDatabase(dim=10000)
    seed_database(db)
    
    assert len(db.experiments) == 7
    assert len(db.vector_store) == 7
    
    # Check if vectors are correctly stored and are bipolar
    for exp_id, vector in db.vector_store.items():
        assert vector.shape == (10000,)
        
    # Check if roles are populated
    assert "Role:Alloy" in db.codebook
    assert "Role:Temperature" in db.codebook

def test_search():
    db = HSMEVectorDatabase(dim=10000)
    seed_database(db)
    
    # Search for Alloy A at 900°C
    query = [
        Entity(type="Alloy", value="Alloy A"),
        Entity(type="Temperature", value="900°C")
    ]
    results = db.search(query, limit=2)
    assert len(results) > 0
    # First result should be EXP-A01 (Alloy A Annealing at 900°C)
    best_match, score = results[0]
    assert best_match.id == "EXP-A01"
    assert score > 0.3  # High similarity since both entities match

def test_counterfactuals():
    db = HSMEVectorDatabase(dim=10000)
    seed_database(db)
    
    # Check counterfactuals for EXP-A01 (Alloy A at 900°C)
    # Alloy A at 950°C (EXP-A02) differs only by Temperature
    cfs = db.get_counterfactuals("EXP-A01")
    assert len(cfs) >= 1
    
    # Verify the details
    cf = cfs[0]
    assert cf["experiment"].id == "EXP-A02"
    assert cf["difference"]["parameter"] == "Temperature"
    assert cf["difference"]["from"] == "900°C"
    assert cf["difference"]["to"] == "950°C"
    
    # Verify that Yield Strength is flagged as an effect
    strength_effect = next(e for e in cf["effects"] if e["property"] == "Yield Strength")
    assert strength_effect["from"] == "620 MPa"
    assert strength_effect["to"] == "690 MPa"

def test_gaps():
    db = HSMEVectorDatabase(dim=10000)
    seed_database(db)
    
    # Check gaps for Alloy and Temperature
    gaps = db.analyze_gaps(["Alloy", "Temperature"])
    assert len(gaps) > 0
    
    # Since Alloy A is tested at 900°C and 950°C, and Alloy B is tested at 900°C, 950°C, 1000°C,
    # the configuration (Alloy A at 1000°C) should be a gap (missing).
    alloy_a_1000_gap = None
    for gap in gaps:
        config_map = {e.type: e.value for e in gap["configuration"]}
        if config_map.get("Alloy") == "Alloy A" and config_map.get("Temperature") == "1000°C":
            alloy_a_1000_gap = gap
            break
            
    assert alloy_a_1000_gap is not None
    # Check if there is a predicted Yield Strength (based on similar experiments, e.g. Alloy A at 950°C and Alloy B at 1000°C)
    predicted_strength = next((e.value for e in alloy_a_1000_gap["predicted_properties"] if e.type == "Yield Strength"), None)
    assert predicted_strength is not None
    assert "MPa" in predicted_strength
