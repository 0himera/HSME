import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_get_experiments():
    response = client.get("/api/experiments")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 7
    assert data[0]["id"] == "EXP-A01"

def test_ingest_experiment():
    payload = {
        "id": "EXP-NEW",
        "name": "New Experimental Alloy",
        "input_entities": [
            {"type": "Alloy", "value": "Alloy Z"},
            {"type": "Temperature", "value": "900°C"}
        ],
        "process_entities": [
            {"type": "Heat Treatment", "value": "Annealing"}
        ],
        "output_entities": [
            {"type": "Yield Strength", "value": "590 MPa"}
        ],
        "evidence": ["test_doc.pdf"],
        "confidence": 0.99
    }
    response = client.post("/api/ingest", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    
    # Confirm it was added
    resp_all = client.get("/api/experiments")
    assert len(resp_all.json()) == 8

def test_search():
    payload = {
        "entities": [
            {"type": "Alloy", "value": "Alloy A"},
            {"type": "Temperature", "value": "900°C"}
        ],
        "limit": 3
    }
    response = client.post("/api/search", json=payload)
    assert response.status_code == 200
    results = response.json()
    assert len(results) > 0
    assert results[0]["experiment"]["id"] == "EXP-A01"
    assert results[0]["similarity"] > 0.3

def test_counterfactuals_and_reasoning():
    # CF search for Alloy A Annealing at 900°C (EXP-A01)
    response = client.get("/api/counterfactuals/EXP-A01")
    assert response.status_code == 200
    cfs = response.json()
    assert len(cfs) >= 1
    assert cfs[0]["experiment"]["id"] == "EXP-A02"
    
    # Causal explanation endpoint
    response = client.get("/api/reason/EXP-A01")
    assert response.status_code == 200
    data = response.json()
    assert data["has_explanation"] is True
    assert "Causal Reasoning Report" in data["explanation"]
    assert "Temperature" in data["explanation"]

def test_gaps_and_enrichment():
    payload = {
        "dimensions": ["Alloy", "Temperature"]
    }
    response = client.post("/api/gaps", json=payload)
    assert response.status_code == 200
    gaps = response.json()
    assert len(gaps) > 0
    
    # Enrich the first gap
    first_gap_config = gaps[0]["configuration"]
    response = client.post("/api/enrich-gap", json=first_gap_config)
    assert response.status_code == 200
    data = response.json()
    assert "hypothesis" in data
    assert "Research Hypothesis" in data["hypothesis"]
