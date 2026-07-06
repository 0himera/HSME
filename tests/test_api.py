import os
import pytest
from unittest.mock import AsyncMock, patch

# Use an isolated test database for API tests
os.environ["HSME_DATABASE_FILE"] = "test_db_state.pkl"

# Clean up test database file before starting
if os.path.exists("test_db_state.pkl"):
    try:
        os.remove("test_db_state.pkl")
    except Exception:
        pass

from fastapi.testclient import TestClient
from backend.app import app

client = TestClient(app)

def test_get_experiments():
    response = client.get("/api/experiments")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 6
    assert data[0]["id"] == "EXP-NI-01"

def test_ingest_experiment():
    payload = {
        "id": "EXP-TEST-INGEST",
        "name": "Тестовый импортированный эксперимент",
        "input_entities": [
            {"type": "Material", "value": "Сульфат кобальта"},
            {"type": "Property", "value": "плотность тока: 200 А/м2"}
        ],
        "process_entities": [
            {"type": "Process", "value": "Электроэкстракция"}
        ],
        "output_entities": [
            {"type": "Material", "value": "Кобальтовый катод"}
        ],
        "evidence": ["test_cobalt.docx"],
        "confidence": 0.95,
        "year": 2024,
        "geography": "RU",
        "source_type": "Статья"
    }
    response = client.post("/api/ingest", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    
    # Confirm it was added
    resp_all = client.get("/api/experiments")
    assert len(resp_all.json()) == 7

def test_search():
    payload = {
        "entities": [
            {"type": "Material", "value": "Хлоридный электролит никеля"},
            {"type": "Property", "value": "pH: 2.0"}
        ],
        "limit": 3
    }
    response = client.post("/api/search", json=payload)
    assert response.status_code == 200
    results = response.json()
    assert len(results) > 0
    assert results[0]["experiment"]["id"] in ["EXP-NI-01", "EXP-NI-03"]

def test_counterfactuals_and_reasoning():
    # CF search for EXP-NI-01
    response = client.get("/api/counterfactuals/EXP-NI-01")
    assert response.status_code == 200
    cfs = response.json()
    assert len(cfs) >= 1
    
    cf_ids = [c["experiment"]["id"] for c in cfs]
    assert "EXP-NI-02" in cf_ids
    
    # Causal explanation endpoint (calls YandexGPT 5.1)
    print("\nCalling API reason endpoint (YandexGPT 5.1)...")
    response = client.get("/api/reason/EXP-NI-01")
    assert response.status_code == 200
    data = response.json()
    assert data["has_explanation"] is True
    assert len(data["explanation"]) > 20

def test_gaps_and_enrichment():
    payload = {
        "dimensions": ["Material", "Facility"]
    }
    response = client.post("/api/gaps", json=payload)
    assert response.status_code == 200
    gaps = response.json()
    assert len(gaps) > 0
    
    # Enrich the first gap (calls YandexGPT 5.1)
    print("\nCalling API enrich-gap endpoint (YandexGPT 5.1)...")
    first_gap_config = gaps[0]["configuration"]
    response = client.post("/api/enrich-gap", json=first_gap_config)
    assert response.status_code == 200
    data = response.json()
    assert "hypothesis" in data
    assert len(data["hypothesis"]) > 20
    
def test_graph_and_statistics():
    # Test graph representation
    response = client.get("/api/graph")
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) > 5
    
    # Test statistics
    response = client.get("/api/statistics")
    assert response.status_code == 200
    stats = response.json()
    assert stats["total_experiments"] >= 6
    assert "Material" in stats["distinct_counts"]

def test_natural_language_search():
    payload = {
        "query": "электроэкстракция никеля при pH < 2.5",
        "limit": 3,
        "paged": True,
        "skip": 0
    }
    response = client.post("/api/search", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "results" in data
    assert "rag_explanation" in data
    
    results = data["results"]
    assert len(results) > 0
    best_match_id = results[0]["experiment"]["id"]
    assert best_match_id in ["EXP-NI-01", "EXP-NI-02", "EXP-NI-03"]


def test_natural_language_search_llm_latency_fields():
    payload = {
        "query": "электроэкстракция никеля при pH < 2.5",
        "limit": 3,
        "paged": True,
        "skip": 0,
    }

    async def mock_synth(*_args, **_kwargs):
        return "### 1. Вывод\nТестовый ответ.", 0.1111, 0.4444

    with patch(
        "backend.routers.search.synthesize_vsa_answer",
        new=AsyncMock(side_effect=mock_synth),
    ):
        response = client.post("/api/search", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert "rag_explanation" in data
    assert data.get("llm_ttft_s") == 0.1111
    assert data.get("llm_ttfa_s") == 0.4444
