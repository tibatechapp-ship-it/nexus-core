"""OpenAPI spec + docs-serving guards (no live server, no network).

``docs/openapi.yaml`` is the public contract. These tests keep it in lockstep
with the real FastAPI routes in BOTH directions: no undocumented route, and no
phantom route promised by the spec. They also prove the Swagger UI is served
from LOCAL assets (no CDN), so the docs work offline.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sse_starlette")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
_SPEC = _ROOT / "docs" / "openapi.yaml"
_SELF = "/api/openapi.yaml"  # the spec endpoint itself is not a documented API path


def _load_workbench_main():
    """Load the repo-root ``main.py`` by explicit path (order-independent).

    A bare ``import main`` resolves to ``src/novamind/main.py`` once the
    novamind suite puts ``src/novamind`` on ``sys.path`` — see test_build_api.py.
    """
    spec = importlib.util.spec_from_file_location(
        "nexus_workbench_main_docs", _ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def client():
    main = _load_workbench_main()
    main.CRAFT_TOKEN = ""  # auth off regardless of the ambient environment
    return TestClient(main.app), main


# ────────────────────────────── serving ──────────────────────────────

def test_health_ok(client):
    c, _ = client
    r = c.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_openapi_yaml_served_with_correct_mime(client):
    c, _ = client
    r = c.get("/api/openapi.yaml")
    assert r.status_code == 200
    assert "openapi:" in r.text
    assert "yaml" in r.headers.get("content-type", "")


def test_swagger_page_is_local_no_cdn(client):
    c, _ = client
    r = c.get("/docs/swagger")
    assert r.status_code == 200
    assert "SwaggerUIBundle" in r.text
    assert "cdn.jsdelivr" not in r.text, "Swagger يعتمد CDN — سينكسر بلا إنترنت"


def test_docs_redirect(client):
    c, _ = client
    r = c.get("/docs", follow_redirects=False)
    assert r.status_code in (301, 302, 307)


def test_vendor_assets_served(client):
    c, _ = client
    css = c.get("/docs/vendor/swagger-ui.css")
    assert css.status_code == 200 and "css" in css.headers.get("content-type", "")
    js = c.get("/docs/vendor/swagger-ui-bundle.js")
    assert js.status_code == 200 and "javascript" in js.headers.get("content-type", "")
    assert c.get("/docs/vendor/nope.js").status_code == 404


def test_craft_empty_query_honest_error(client):
    c, _ = client
    r = c.post("/api/craft", json={})
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is False and body.get("error")


# ────────────────────────── drift guard (both ways) ──────────────────────────

def _spec_api_paths() -> set[str]:
    txt = _SPEC.read_text(encoding="utf-8")
    return set(re.findall(r"^  (/api/[\w/{}.:\-]+):", txt, re.M)) - {_SELF}


def test_spec_paths_match_app_both_ways(client):
    _, main = client
    app_paths = {p for p in main.app.openapi()["paths"]
                 if p.startswith("/api/")} - {_SELF}
    spec_paths = _spec_api_paths()
    undocumented = app_paths - spec_paths
    phantom = spec_paths - app_paths
    assert not undocumented, f"مسارات حقيقية غير موثقة: {sorted(undocumented)}"
    assert not phantom, f"مسارات موهمة غير منفَّذة: {sorted(phantom)}"


def test_spec_no_phantom_fields():
    txt = _SPEC.read_text(encoding="utf-8")
    for lie in ("size_bytes:", "proof.command", "success:"):
        assert lie not in txt, f"المواصفة تعد بحقل غير منفَّذ: {lie}"
