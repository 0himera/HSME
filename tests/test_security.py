import os
import pytest

# Use an isolated test database for security tests
os.environ["HSME_DATABASE_FILE"] = "test_db_state.pkl"

from fastapi.testclient import TestClient
from backend.app import app

client = TestClient(app)

def test_role_access_rights():
    # 1. Administrator can access ingest-corpus
    headers_admin = {"X-User-Name": "test_admin", "X-User-Role": "Administrator"}
    response = client.post("/api/ingest-corpus", headers=headers_admin)
    # Since ingestion might already be running or completed, it should start or say already running.
    # The status code must not be 403.
    assert response.status_code in [200, 400]

    # 2. Researcher cannot access ingest-corpus (should get 403)
    headers_researcher = {"X-User-Name": "test_researcher", "X-User-Role": "Researcher"}
    response = client.post("/api/ingest-corpus", headers=headers_researcher)
    assert response.status_code == 403

    # 3. External Partner cannot access gaps (should get 403)
    headers_partner = {"X-User-Name": "test_partner", "X-User-Role": "External Partner"}
    response = client.post("/api/gaps", json={"dimensions": ["Material"]}, headers=headers_partner)
    assert response.status_code == 403

def test_privacy_filtering():
    # External Partner should NOT see sensitive experiments in list
    headers_partner = {"X-User-Name": "test_partner", "X-User-Role": "External Partner"}
    response = client.get("/api/experiments", headers=headers_partner)
    assert response.status_code == 200
    experiments = response.json()
    # KGMK electrowinning (EXP-NI-01) is sensitive, so it should not be in the list
    ids = [e["id"] for e in experiments]
    assert "EXP-CU-01" in ids
    assert "EXP-NI-01" not in ids

    # Administrator SHOULD see sensitive experiments in list
    headers_admin = {"X-User-Name": "test_admin", "X-User-Role": "Administrator"}
    response = client.get("/api/experiments", headers=headers_admin)
    assert response.status_code == 200
    experiments_admin = response.json()
    ids_admin = [e["id"] for e in experiments_admin]
    assert "EXP-NI-01" in ids_admin

def test_search_privacy():
    # External Partner searching for nickel хлоридный электролит should not get sensitive KGMK experiments
    headers_partner = {"X-User-Name": "test_partner", "X-User-Role": "External Partner"}
    payload = {
        "entities": [
            {"type": "Material", "value": "Хлоридный электролит никеля"}
        ],
        "limit": 5
    }
    response = client.post("/api/search", json=payload, headers=headers_partner)
    assert response.status_code == 200
    results = response.json()
    # KGMK experiments are sensitive, so search should return empty or other non-sensitive results
    found_ids = [r["experiment"]["id"] for r in results]
    assert "EXP-NI-01" not in found_ids

def test_audit_logging():
    # Perform an action as researcher
    headers_researcher = {"X-User-Name": "bill", "X-User-Role": "Researcher"}
    client.post("/api/gaps", json={"dimensions": ["Material", "Facility"]}, headers=headers_researcher)

    # Admin checks audit logs
    headers_admin = {"X-User-Name": "admin", "X-User-Role": "Administrator"}
    response = client.get("/api/audit-logs", headers=headers_admin)
    assert response.status_code == 200
    logs = response.json()
    
    # Verify the action was logged
    researcher_logs = [l for l in logs if l["username"] == "bill" and l["action"] == "GAP_ANALYSIS"]
    assert len(researcher_logs) > 0
    assert "Material" in researcher_logs[0]["details"]

def test_pagination():
    # Request experiments list paged
    headers_admin = {"X-User-Name": "admin", "X-User-Role": "Administrator"}
    response = client.get("/api/experiments?skip=0&limit=2&paged=true", headers=headers_admin)
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "experiments" in data
    assert len(data["experiments"]) <= 2
    assert data["total"] >= 6
