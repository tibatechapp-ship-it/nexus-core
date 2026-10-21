"""Tests for GET /health endpoint (v1.38.0)."""
from fastapi.testclient import TestClient

import nexus_agent


def test_health_returns_200_and_ok():
    client = TestClient(nexus_agent.app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


def test_health_includes_timestamp():
    client = TestClient(nexus_agent.app)
    response = client.get("/health")
    body = response.json()
    assert "timestamp" in body
    assert isinstance(body["timestamp"], (int, float))
    assert body["timestamp"] > 0
