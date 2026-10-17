"""Training pipeline — HTTP surface (``/api/training/*``).

Skipped when FastAPI is not installed, so the stdlib-only phone gate stays green.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from novamind.training import (  # noqa: E402
    GRADUATION_MIN_SCORE,
    TrainingEngine,
    TrainingStore,
)
from novamind.training.api import build_router, register  # noqa: E402

#: Routes the pipeline must expose (guards accidental renames/drops).
EXPECTED_ROUTES = (
    "/api/training/status",
    "/api/training/agents",
    "/api/training/plan/{agent_id}",
    "/api/training/run",
    "/api/training/batch",
    "/api/training/runs",
    "/api/training/runs/{run_id}",
    "/api/training/certificates",
)


def _engine(tmp_path: Path) -> TrainingEngine:
    """An engine on a throwaway DB with no genome side-effects."""
    return TrainingEngine(
        store=TrainingStore(tmp_path / "training.db"), feed_genome=False
    )


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """A bare app carrying only the training router."""
    app = FastAPI()
    app.include_router(build_router(_engine(tmp_path)))
    return TestClient(app)


@pytest.fixture()
def mounted(tmp_path: Path) -> TestClient:
    """The routes behind ``mount("/")`` — how the unified gateway serves them."""
    engine_app = FastAPI()
    register(engine_app, _engine(tmp_path))
    parent = FastAPI()

    @parent.get("/api/ping")
    async def ping() -> dict:
        return {"ok": True}

    parent.mount("/", engine_app)
    return TestClient(parent)


def test_build_router_declares_the_public_surface() -> None:
    paths = {route.path for route in build_router().routes}
    assert set(EXPECTED_ROUTES) <= paths


def test_routes_survive_an_asgi_mount(mounted: TestClient) -> None:
    """Regression: ``include_router`` is deferred and 404s inside a mount.

    The unified gateway mounts this app at ``/``, so the routes must be added
    as concrete entries — ``register`` does that, ``include_router`` does not.
    """
    assert mounted.get("/api/ping").status_code == 200
    assert mounted.get("/api/training/status").status_code == 200
    assert mounted.get("/api/training/plan/coder").status_code == 200
    assert mounted.post(
        "/api/training/run", json={"agent_id": "coder", "quality": 0.95}
    ).status_code == 200


def _train(client: TestClient, agent_id: str = "coder", **extra) -> dict:
    resp = client.post("/api/training/run", json={"agent_id": agent_id, **extra})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── status / introspection ───────────────────────────────────────────────
def test_status_is_empty_before_any_run(client: TestClient) -> None:
    payload = client.get("/api/training/status").json()
    assert payload["runs"] == 0
    assert payload["certificates"] == 0
    assert payload["certification_rate"] == 0.0
    assert payload["min_score"] == GRADUATION_MIN_SCORE
    assert payload["certified_agents"] == 0


def test_status_after_a_successful_run(client: TestClient) -> None:
    _train(client, quality=0.95)
    payload = client.get("/api/training/status").json()
    assert payload["runs"] == 1
    assert payload["certified"] == 1
    assert payload["certificates"] == 1
    assert payload["certified_agents"] == 1
    assert payload["certification_rate"] == 1.0


def test_agents_lists_the_latest_run_and_certificate(client: TestClient) -> None:
    run = _train(client, quality=0.95)
    payload = client.get("/api/training/agents").json()
    assert payload["count"] == 1
    row = payload["agents"][0]
    assert row["agent_id"] == "coder"
    assert row["latest_run"]["run_id"] == run["run_id"]
    assert row["certificate_id"].startswith("cert_")


def test_agents_omits_the_certificate_for_an_uncertified_agent(
    client: TestClient,
) -> None:
    _train(client, agent_id="weak", quality=0.6)
    row = client.get("/api/training/agents").json()["agents"][0]
    assert row["agent_id"] == "weak"
    assert "certificate_id" not in row


def test_plan_exposes_the_curriculum(client: TestClient) -> None:
    payload = client.get("/api/training/plan/coder").json()
    assert payload["agent_id"] == "coder"
    assert payload["module_count"] == len(payload["modules"])
    assert payload["latest_run"] is None
    assert all(m["min_score"] > 0 for m in payload["modules"])


def test_plan_accepts_an_explicit_spec(client: TestClient) -> None:
    payload = client.get(
        "/api/training/plan/coder", params={"spec": "security"}
    ).json()
    assert payload["spec"] == "security"
    assert "owasp_top10" in [m["name"] for m in payload["modules"]]


# ── runs ─────────────────────────────────────────────────────────────────
def test_run_returns_the_recorded_run(client: TestClient) -> None:
    run = _train(client, quality=0.95)
    assert run["agent_id"] == "coder"
    assert run["verdict"] == "graduated"
    assert run["certified"] is True
    assert run["phases"]
    assert run["detail"]["modules_total"] == len(run["phases"])


def test_runs_history_and_lookup(client: TestClient) -> None:
    first = _train(client, quality=0.95)
    second = _train(client, quality=0.95)

    listing = client.get("/api/training/runs").json()
    assert listing["count"] == 2
    assert {r["run_id"] for r in listing["runs"]} == {first["run_id"], second["run_id"]}

    by_id = client.get(f"/api/training/runs/{first['run_id']}").json()
    assert by_id["run_id"] == first["run_id"]

    filtered = client.get("/api/training/runs", params={"agent_id": "ghost"}).json()
    assert filtered["count"] == 0


def test_unknown_run_is_404(client: TestClient) -> None:
    assert client.get("/api/training/runs/tr_missing").status_code == 404


def test_batch_trains_every_agent(client: TestClient) -> None:
    resp = client.post(
        "/api/training/batch",
        json={"agent_ids": ["coder", "tester"], "quality": 0.95},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["count"] == 2
    assert payload["graduated"] == 2
    assert {r["agent_id"] for r in payload["runs"]} == {"coder", "tester"}


def test_batch_rejects_an_empty_list(client: TestClient) -> None:
    assert client.post("/api/training/batch", json={"agent_ids": []}).status_code == 400


def test_run_validates_the_quality_range(client: TestClient) -> None:
    resp = client.post(
        "/api/training/run", json={"agent_id": "coder", "quality": 2.0}
    )
    assert resp.status_code == 422


def test_run_requires_an_agent_id(client: TestClient) -> None:
    assert client.post("/api/training/run", json={}).status_code == 422


# ── certificates: the stated negative ────────────────────────────────────
def test_a_weak_agent_earns_no_certificate(client: TestClient) -> None:
    run = _train(client, agent_id="weak", quality=0.60)
    assert run["certified"] is False
    assert run["final_score"] < GRADUATION_MIN_SCORE
    assert run["verdict"] == "failed"
    assert client.get("/api/training/certificates").json()["count"] == 0
    assert client.get(
        "/api/training/certificates", params={"agent_id": "weak"}
    ).json()["count"] == 0
    assert client.get("/api/training/status").json()["certificates"] == 0


def test_a_mediocre_agent_earns_no_certificate(client: TestClient) -> None:
    run = _train(client, agent_id="mid", quality=0.72)
    assert run["certified"] is False
    assert run["verdict"] == "needs_retraining"
    assert client.get("/api/training/certificates").json()["count"] == 0


def test_certificates_match_the_run_they_were_issued_for(
    client: TestClient,
) -> None:
    run = _train(client, quality=0.95)
    certs = client.get("/api/training/certificates").json()["certificates"]
    assert len(certs) == 1
    cert = certs[0]
    assert cert["certificate_id"].startswith("cert_")
    assert cert["run_id"] == run["run_id"]
    assert cert["agent_id"] == "coder"
    assert cert["score"] == run["final_score"]
    assert cert["issued_at"] > 0
    assert cert["payload"]["certificate_id"] == cert["certificate_id"]
    assert cert["payload"]["run_id"] == run["run_id"]
    # Signing is optional (cryptography may be absent): either a real signature
    # or an empty string, never a fabricated one.
    assert isinstance(cert["signature"], str)
