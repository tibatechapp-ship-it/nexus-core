"""Tests for GET /health endpoint (v1.38.0)."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sse_starlette")

from fastapi.testclient import TestClient  # noqa: E402

import nexus_agent  # noqa: E402


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
