"""ZUI contract tests (ب3.1/ب3.3) — خطة التناغم docs/harmony-plan.md.

العقد: واجهة ويب واحدة (web/zui/) تخدمها ثلاث نقاط دخول — /ui و / في
البوابة، / في المحرك المستقل، / في workbench main.py — مكوّن واحد لا نسخ.
بلا CDN ولا خطوط خارجية: كل الأصول محلية (vendor/zui) والواجهة تعمل
أوفلاين. صفحات الواجهة لا تحذف أي مسار API من العقد (ب3.4).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
ZUI = _ROOT / "web" / "zui"
INDEX = ZUI / "index.html"


def _load_by_path(name: str, filename: Path):
    spec = importlib.util.spec_from_file_location(name, filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def zui_html() -> str:
    return INDEX.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def gateway(env=None):
    """البوابة الموحدة nexus_agent.py — نفس آلية تحميل test_nexus_agent."""
    mod = _load_by_path("zui_nexus_agent", _ROOT / "src" / "legacy_root" / "nexus_agent.py")
    with TestClient(mod.app) as client:
        yield client


# ── مصدر واحد لا نسخ ────────────────────────────────────────────────────
def test_zui_assets_exist() -> None:
    """مكوّن ZUI كامل: html + css + js + manifest + sw + icon + offline."""
    for name in ("index.html", "css/zui.css", "js/zui.js",
                 "manifest.json", "sw.js", "icon.svg", "offline.html"):
        assert (ZUI / name).exists(), f"missing ZUI asset: {name}"


def test_zui_is_self_contained_no_cdn(zui_html: str) -> None:
    """عقد الأوفلاين: لا CDN ولا خطوط خارجية — كل الروابط نسبية محلية."""
    for host in ("cdn.", "googleapis", "unpkg", "jsdelivr", "fonts.googleapis"):
        assert host not in zui_html, f"external dependency found: {host}"
    for asset in ("/zui/css/zui.css", "/zui/js/zui.js", "/zui/manifest.json",
                  "/vendor/github-dark.min.css"):
        assert asset in zui_html, f"missing local asset reference: {asset}"


def test_zui_has_the_four_panels(zui_html: str) -> None:
    """اللوحات الأربع معلنة في الهيكل: وكلاء، مجلس، تتبع، تقييم."""
    for tab in ("agents", "council", "traces", "monitor"):
        assert f'data-tab="{tab}"' in zui_html


def test_zui_manifest_is_valid_json() -> None:
    """مانيفست PWA صالح: اسم وخلفية داكنة وأيقونة محلية."""
    import json

    manifest = json.loads((ZUI / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "Nexus ZUI"
    assert manifest["background_color"] == "#0d0f13"
    assert manifest["icons"][0]["src"] == "/zui/icon.svg"


# ── الثلاث نقاط تخدم نفس الصفحة (ب3.3) ─────────────────────────────────
def test_gateway_ui_serves_zui(gateway) -> None:
    """/ui في البوابة = ZUI بعنوانها وشارة التوجيه."""
    resp = gateway.get("/ui")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Nexus ZUI" in resp.text


def test_gateway_root_serves_zui(gateway) -> None:
    """الجذر في البوابة (عبر mount المحرك) = ZUI نفسها."""
    resp = gateway.get("/")
    assert resp.status_code == 200
    assert "Nexus ZUI" in resp.text


def test_gateway_zui_static_assets(gateway) -> None:
    """/zui mount يخدم css وjs وmanifest وsw."""
    for path, marker in (
        ("/zui/css/zui.css", "--accent"),
        ("/zui/js/zui.js", "sendMessage"),
        ("/zui/manifest.json", '"name": "Nexus ZUI"'),
        ("/zui/icon.svg", "<svg"),
    ):
        resp = gateway.get(path)
        assert resp.status_code == 200, path
        assert marker in resp.text, path


def test_gateway_monitor_endpoint(gateway, tmp_path, monkeypatch) -> None:
    """/api/monitor — تقييم حتمي من سجل مصنوع، وغيابه ⇒ {} معلن."""
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        '{"ts":"t1","agent":"coder","tool":"run","duration_ms":10.0,"outcome":"ok"}\n'
        * 6, encoding="utf-8")
    monkeypatch.setenv("NEXUS_TRACE_PATH", str(trace))
    data = gateway.get("/api/monitor").json()
    assert data["ok"] is True
    assert data["evaluations"]["coder"]["runs"] == 6
    assert data["evaluations"]["coder"]["grade"] == "monitor-clear"
    assert data["summary"]["monitor-clear"] == 1
    # سجل غائب ⇒ {} معلن — لا انفجار
    monkeypatch.setenv("NEXUS_TRACE_PATH", str(tmp_path / "never.jsonl"))
    empty = gateway.get("/api/monitor").json()
    assert empty["ok"] is True
    assert empty["evaluations"] == {}


def test_workbench_and_engine_serve_same_component() -> None:
    """ب3.3: main.py وunified_agent.py يقرآن نفس الملف — مكوّن واحد لا نسخ."""
    main_src = (_ROOT / "main.py").read_text(encoding="utf-8")
    engine_src = (_ROOT / "src" / "legacy_root" / "unified_agent.py").read_text(encoding="utf-8")
    assert '"web", "zui", "index.html"' in main_src or \
        'os.path.join(BASE_DIR, "web", "zui", "index.html")' in main_src
    assert '"web" / "zui" / "index.html"' in engine_src
    # الصفحة نفسها تحتوي شارة الواجهة الوحيدة
    html = INDEX.read_text(encoding="utf-8")
    assert html.count("<!doctype html>") == 1


def test_no_reference_to_deleted_ui_survives() -> None:
    """ب3.2: لا مرجع حي للواجهات المحذوفة في الكود الحي والسكربتات."""
    live_files = [
        _ROOT / "main.py",
        _ROOT / "src" / "legacy_root" / "nexus_agent.py",
        _ROOT / "src" / "legacy_root" / "unified_agent.py",
    ]
    banned = ("unified_ui.html", "studio_server.py", "dashboard.html",
              "immune_dashboard_api", "Dockerfile.backend")
    for path in live_files:
        text = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"{path.name} still references {token}"
    # الملفات المحذوفة لا وجود لها فعلاً
    for gone in ("index.html", "web/unified_ui.html", "studio",
                 "src/web", "src/novamind/web_platform",
                 "src/novamind/dashboard", "Dockerfile.backend",
                 "scripts/nexus-web"):
        assert not (_ROOT / gone).exists(), f"deleted UI still present: {gone}"
