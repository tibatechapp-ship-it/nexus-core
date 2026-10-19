"""Execution-verification HTTP surface (``/api/verify/*``).

Skipped when FastAPI is absent so the stdlib-only phone gate stays green.
The engine/generator calls are monkeypatched OR run against the real sandbox
(guarded by ``requires_sandbox``) — never against the network.
"""

from __future__ import annotations

import sys
import types

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.verify import engine as E  # noqa: E402
from src.verify import api as A  # noqa: E402
from tests.conftest import requires_sandbox  # noqa: E402

EXPECTED_ROUTES = (
    "/api/verify/tools",
    "/api/verify/run",
    "/api/verify/fix",
)


@pytest.fixture()
def app() -> FastAPI:
    obj = FastAPI()
    A.register(obj)
    return obj


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def mounted() -> TestClient:
    """The routes behind ``mount("/")`` — how the unified gateway serves them."""
    engine_app = FastAPI()
    A.register(engine_app)
    parent = FastAPI()

    @parent.get("/api/ping")
    async def ping() -> dict:
        return {"ok": True}

    parent.mount("/", engine_app)
    return TestClient(parent)


def test_build_router_declares_the_public_surface() -> None:
    paths = {route.path for route in A.build_router().routes}
    assert set(EXPECTED_ROUTES) <= paths


def test_register_returns_the_router(app: FastAPI) -> None:
    router = A.register(app)
    assert {r.path for r in router.routes} >= set(EXPECTED_ROUTES)


def test_routes_survive_an_asgi_mount(mounted: TestClient) -> None:
    """Regression: ``include_router`` is deferred and 404s inside a mount."""
    assert mounted.get("/api/ping").status_code == 200
    assert mounted.get("/api/verify/tools").status_code == 200


def test_tools_reports_the_languages(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(A, "_languages", lambda: ["bash", "python"])
    payload = client.get("/api/verify/tools").json()
    assert payload == {
        "ok": True,
        "available": True,
        "languages": ["bash", "python"],
        "max_attempts": E.MAX_ATTEMPTS,
        "generator": "llm",
    }


def test_tools_reports_unavailable_when_no_sandbox(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(A, "_languages", list)
    assert client.get("/api/verify/tools").json()["available"] is False


def test_languages_reads_the_real_sandbox_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = types.ModuleType("exec_sandbox")
    mod.LANGS = {"python": {}, "bash": {}}
    monkeypatch.setitem(sys.modules, "exec_sandbox", mod)
    assert A._languages() == ["bash", "python"]


def test_languages_returns_empty_when_the_sandbox_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "exec_sandbox", None)
    assert A._languages() == []


def test_run_returns_the_verdict_dict(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}

    def fake(code, *, language, tests, stdin, timeout):
        captured.update(code=code, language=language, tests=tests, timeout=timeout)
        return E.VerificationResult(True, "ok", code, language, 1, ({"stdout": "42"},))

    monkeypatch.setattr(A, "verify_by_execution", fake)
    resp = client.post("/api/verify/run", json={"code": "print(42)", "timeout": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["passed"] is True
    assert body["reason"] == "ok"
    assert body["detail"] == [{"stdout": "42"}]
    assert captured == {"code": "print(42)", "language": "python", "tests": "", "timeout": 5}


def test_run_rejects_an_empty_body(client: TestClient) -> None:
    assert client.post("/api/verify/run", json={"code": ""}).status_code == 422


def test_run_rejects_an_out_of_range_timeout(client: TestClient) -> None:
    assert client.post(
        "/api/verify/run", json={"code": "x", "timeout": 99}
    ).status_code == 422


def test_fix_delegates_to_the_generator(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}

    def fake_loop(task, code, *, language, tests, stdin, timeout, max_attempts, generate):
        captured.update(
            task=task, code=code, max_attempts=max_attempts, generate=generate
        )
        return E.VerificationResult(True, "ok", code, language, 2, ())

    monkeypatch.setattr(A, "fix_loop", fake_loop)
    resp = client.post(
        "/api/verify/fix",
        json={"code": "broken", "task": "fix it", "max_attempts": 4},
    )
    assert resp.status_code == 200
    assert resp.json()["attempts"] == 2
    assert captured["task"] == "fix it"
    assert captured["max_attempts"] == 4
    assert captured["generate"] is A.llm_generate


def test_fix_caps_attempts_at_the_engine_maximum(client: TestClient) -> None:
    assert client.post(
        "/api/verify/fix", json={"code": "x", "max_attempts": E.MAX_ATTEMPTS + 1}
    ).status_code == 422


# ── real sandbox (guarded — the module is gitignored) ─────────────────────
@requires_sandbox
def test_run_executes_real_code(client: TestClient) -> None:
    body = client.post("/api/verify/run", json={"code": "print(6 * 7)"}).json()
    assert body["passed"] is True
    assert "42" in body["detail"][0]["stdout"]


@requires_sandbox
def test_run_flags_a_wrong_answer(client: TestClient) -> None:
    resp = client.post(
        "/api/verify/run",
        json={"code": "print(1)", "tests": "assert False, 'nope'"},
    )
    assert resp.json()["passed"] is False
    assert resp.json()["reason"] == "exit 1"
