"""OpenAPI spec + docs-serving guards (no live server, no network).

``docs/openapi.yaml`` is the public contract, and this repo serves THREE apps:

* ``main.py`` — the workbench (council/craft API; also serves this spec)
* ``unified_agent.py`` — the gateway (workspace/chat/pipeline/training/…)
* ``nexus_agent.py`` — the launcher; it fronts the gateway and owns routes
  neither of the other two serves (`/api/mcp/tools`, exec sandbox, vendor mount)

The guard loads all three and compares the union of their real routes against
the spec in BOTH directions: no undocumented route, no phantom route, no
invented parameter, no missing guard response. It also proves the Swagger UI is
served from LOCAL assets (no CDN), so the docs work offline.
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
_VERBS = ("get", "post", "put", "patch", "delete")
# The launcher imports flat modules from tools/ by bare name, exactly like the
# real launcher does; without this it silently drops /api/settings/provider and
# /api/ollama/chat and the union would under-report the surface.
_TOOLS_DIR = _ROOT / "tools"
_MUTATING = ("post", "put", "patch", "delete")


def _load_by_path(name: str, filename: str):
    """Load a repo-root module by explicit path (order-independent).

    A bare ``import main`` resolves to ``src/novamind/main.py`` once the
    novamind suite puts ``src/novamind`` on ``sys.path`` — see test_build_api.py.
    """
    spec = importlib.util.spec_from_file_location(name, _ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def apps():
    """The three live apps: workbench + gateway + launcher."""
    import sys

    if str(_TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(_TOOLS_DIR))
    workbench = _load_by_path("nexus_workbench_main_docs", "main.py")
    workbench.CRAFT_TOKEN = ""  # auth off regardless of the ambient environment
    gateway = _load_by_path("nexus_gateway_docs", "unified_agent.py")
    launcher = _load_by_path("nexus_launcher_docs", "nexus_agent.py")
    return {"main.py": workbench, "unified_agent.py": gateway, "nexus_agent.py": launcher}


@pytest.fixture()
def client(apps):
    return TestClient(apps["main.py"].app), apps["main.py"]


@pytest.fixture(scope="module")
def spec() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(_SPEC.read_text(encoding="utf-8"))


def _live_paths(app) -> dict[str, set[str]]:
    """path → verbs actually served by this app (spec endpoint excluded)."""
    paths: dict[str, set[str]] = {}
    for path, item in app.app.openapi()["paths"].items():
        if not path.startswith("/api/") or path == _SELF:
            continue
        verbs = {v for v in item if v in _VERBS}
        if verbs:
            paths[path] = verbs
    return paths


def _live_union(apps) -> dict[str, set[str]]:
    union: dict[str, set[str]] = {}
    for app in apps.values():
        for path, verbs in _live_paths(app).items():
            union.setdefault(path, set()).update(verbs)
    return union


def _spec_paths(spec: dict) -> dict[str, set[str]]:
    return {
        path: {v for v in item if v in _VERBS}
        for path, item in spec["paths"].items()
    }


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


# ────────────────────────── drift guard (both apps) ──────────────────────────


def test_spec_paths_match_the_apps_both_ways(spec, apps):
    """Union(workbench, gateway) == spec, in both directions."""
    live = _live_union(apps)
    documented = _spec_paths(spec)
    undocumented = sorted(set(live) - set(documented))
    phantom = sorted(set(documented) - set(live))
    assert not undocumented, f"مسارات حقيقية غير موثقة: {undocumented}"
    assert not phantom, f"مسارات موهمة غير منفَّذة: {phantom}"


def test_spec_verbs_match_the_apps(spec, apps):
    """Each path documents exactly the verbs that path really serves."""
    live = _live_union(apps)
    documented = _spec_paths(spec)
    for path in sorted(set(live) & set(documented)):
        assert live[path] == documented[path], (
            f"{path}: التطبيق يخدم {sorted(live[path])} والمواصفة توثّق {sorted(documented[path])}"
        )


def test_every_operation_declares_its_owning_app(spec, apps):
    """`x-app` must name an app that really serves the path.

    The two apps run on different ports; a reader must know which one to call.
    """
    live_by_app = {name: _live_paths(app) for name, app in apps.items()}
    for path, item in spec["paths"].items():
        served_by = {name for name, paths in live_by_app.items() if path in paths}
        assert set(item.get("x-served-by", [])) == served_by, (
            f"{path}: x-served-by={item.get('x-served-by')} بينما الحقيقة {sorted(served_by)}"
        )
        for verb, op in item.items():
            if verb not in _VERBS:
                continue
            assert op.get("x-app") in served_by, (
                f"{verb.upper()} {path}: x-app={op.get('x-app')} لا يخدم هذا المسار"
            )


def test_no_undocumented_parameter(spec, apps):
    """Every path/query parameter the declaring app accepts is in the spec."""
    schemas = {name: app.app.openapi()["paths"] for name, app in apps.items()}
    problems = []
    for path, item in spec["paths"].items():
        for verb, op in item.items():
            if verb not in _VERBS:
                continue
            live = schemas[op["x-app"]].get(path, {}).get(verb, {})
            live_params = {(p["name"], p["in"]) for p in live.get("parameters", [])}
            doc_params = {(p["name"], p["in"]) for p in op.get("parameters", [])}
            if live_params - doc_params:
                problems.append(f"{verb.upper()} {path}: undocumented {sorted(live_params - doc_params)}")
            if doc_params - live_params:
                problems.append(f"{verb.upper()} {path}: phantom {sorted(doc_params - live_params)}")
            # A handler that reads request.json() itself declares no body in the
            # generated schema; documenting one is legitimate ONLY when the
            # operation says so with x-raw-body.
            if live.get("requestBody") and not op.get("requestBody"):
                problems.append(f"{verb.upper()} {path}: body declared by the app but not documented")
            if op.get("requestBody") and not live.get("requestBody") and not op.get("x-raw-body"):
                problems.append(
                    f"{verb.upper()} {path}: undocumented body contract "
                    f"(set x-raw-body if the handler reads raw JSON)"
                )
    assert not problems, "انحراف المعاملات:\n" + "\n".join(problems)


def test_mutating_routes_document_the_access_guard(spec):
    """كل مسار متغيّر موثّق يشرح 401/429 — لأن الحارس يعترضها قبل التنفيذ."""
    missing = []
    for path, item in spec["paths"].items():
        for verb, op in item.items():
            if verb not in _MUTATING:
                continue
            codes = set(op.get("responses", {}))
            if not {"401", "429"} <= codes:
                missing.append(f"{verb.upper()} {path} → {sorted(codes)}")
    assert not missing, "مسارات متغيّرة بلا 401/429:\n" + "\n".join(missing)


def test_spec_no_phantom_fields():
    txt = _SPEC.read_text(encoding="utf-8")
    for lie in ("size_bytes:", "proof.command", "success:"):
        assert lie not in txt, f"المواصفة تعد بحقل غير منفَّذ: {lie}"


# ────────────────────────── structural integrity ──────────────────────────


def test_every_ref_resolves(spec):
    raw = _SPEC.read_text(encoding="utf-8")
    refs = set(re.findall(r"\$ref: '#/components/(\w+)/([A-Za-z0-9_]+)'", raw))
    missing = [(kind, name) for kind, name in refs if name not in spec["components"].get(kind, {})]
    assert not missing, f"$ref إلى مكوّن غير موجود: {sorted(missing)}"


def test_no_unused_components(spec):
    raw = _SPEC.read_text(encoding="utf-8")
    used_schemas = {
        name
        for kind, name in re.findall(r"\$ref: '#/components/(\w+)/([A-Za-z0-9_]+)'", raw)
        if kind == "schemas"
    }
    used_responses = {
        name
        for kind, name in re.findall(r"\$ref: '#/components/(\w+)/([A-Za-z0-9_]+)'", raw)
        if kind == "responses"
    }
    declared_schemas = set(spec["components"]["schemas"])
    declared_responses = set(spec["components"].get("responses", {}))
    assert declared_schemas == used_schemas, (
        f"مكوّنات schemas غير مستخدمة: {sorted(declared_schemas - used_schemas)} · "
        f"مستخدمة وغير معرَّفة: {sorted(used_schemas - declared_schemas)}"
    )
    assert declared_responses == used_responses, (
        f"مكوّنات responses غير مستخدمة: {sorted(declared_responses - used_responses)}"
    )


def test_operation_ids_are_unique_and_tags_declared(spec):
    tags = {t["name"] for t in spec["tags"]}
    seen: dict[str, str] = {}
    for path, item in spec["paths"].items():
        for verb, op in item.items():
            if verb not in _VERBS:
                continue
            where = f"{verb.upper()} {path}"
            op_id = op.get("operationId")
            assert op_id, f"{where} بلا operationId"
            assert op_id not in seen, f"operationId مكرّر: {op_id} ({where} و {seen[op_id]})"
            seen[op_id] = where
            assert op.get("summary"), f"{where} بلا summary"
            assert set(op.get("tags", [])) <= tags, f"{where} يستعمل tag غير معلَن"


def test_path_parameters_are_declared(spec):
    """`{id}` in the template must appear as an `in: path` parameter."""
    for path, item in spec["paths"].items():
        names = set(re.findall(r"\{(\w+)\}", path))
        for verb, op in item.items():
            if verb not in _VERBS:
                continue
            declared = {p["name"] for p in op.get("parameters", []) if p.get("in") == "path"}
            assert declared == names, f"{verb.upper()} {path}: path params {sorted(names)} ≠ {sorted(declared)}"


def test_surface_size_is_pinned(spec, apps):
    """Guard the size itself: a route silently disappearing is drift too.

    Reads the live counts and compares them with the spec, so a fixture that
    fails to import an optional route family (provider settings, ollama) shows up
    as a red test instead of a quietly smaller documented surface.
    """
    live = _live_union(apps)
    ops = sum(len(v) for v in live.values())
    documented = _spec_paths(spec)
    assert len(documented) == len(live), f"{len(documented)} مساراً موثّقاً مقابل {len(live)} حقيقياً"
    assert ops == sum(len(v) for v in documented.values())
    assert ops >= 80, f"السطح تقلّص إلى {ops} عملية — تحقّق من أن كل عائلة مسارات تُستورد"


# ────────────────────────── version lockstep (F2 guard) ──────────────────────────


def _spec_version() -> str:
    """`info.version` من المواصفة (أول تطابق لصف version داخل info)."""
    match = re.search(
        r"^\s+version:\s*['\"]?([\d.]+)['\"]?\s*$",
        _SPEC.read_text(encoding="utf-8"), re.M)
    assert match, "لا يوجد info.version في المواصفة"
    return match.group(1)


def test_spec_version_matches_package_version():
    """`info.version` في المواصفة = `src.__version__` (المصدر الواحد).

    هذا هو الثقب الذي سبّب F2: بقي `docs/openapi.yaml` على 1.12.1 ثلاثة
    إصدارات بينما التطبيق تقدّم، ولم يكن هناك أي اختبار يلاحظ.
    """
    from src import __version__

    assert _spec_version() == __version__, (
        f"انحراف إصدار المواصفة: openapi.yaml={_spec_version()} "
        f"vs src.__version__={__version__}"
    )


def test_health_version_matches_spec(client):
    """`/api/health` يعلن نفس إصدار المواصفة — لا مصدر ثالث متقادم."""
    c, _ = client
    assert c.get("/api/health").json()["version"] == _spec_version()


# ────────────────────────── spec integrity ──────────────────────────


def test_spec_is_valid_yaml(spec):
    """المواصفة تُقرأ بمحلّل YAML حقيقي — لا بـregex فقط."""
    assert str(spec["openapi"]).startswith("3.")
    assert spec["paths"], "المواصفة بلا مسارات"
    assert spec["info"]["version"] == _spec_version()
    for path, ops in spec["paths"].items():
        for verb, op in ops.items():
            if verb not in _VERBS:
                continue
            assert op.get("responses"), f"{verb.upper()} {path} بلا استجابات"
            for code, response in op["responses"].items():
                assert "$ref" in response or response.get("description"), (
                    f"{verb.upper()} {path} → {code} بلا وصف أو $ref"
                )
