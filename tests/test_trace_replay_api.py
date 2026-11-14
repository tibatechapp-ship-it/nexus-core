"""اختبارات Trace Replay API (م3) — جرد الجلسات وخطوات replay.

Offline بالكامل: نكتب جلسات مؤقتة عبر ``NEXUS_TRACES_DIR`` ولا نلمس
``runs/`` الحقيقي، ولا مزوّد شبكة في أي مسار.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.observability.otrace import DeepTracer

_ROOT = Path(__file__).resolve().parents[1]


def _load_gateway() -> Any:
    """حمّل البوابة الموحدة (unified_agent.py) — مسارات التتبع تعيش فيها
    بعد حذف اللوحة القديمة (v1.61.0: نقلت المسارات لا اختباراتها)."""
    name = "_nexus_gateway_trace_replay"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, _ROOT / "src" / "legacy_root" / "unified_agent.py")
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


client = TestClient(_load_gateway().app)


@pytest.fixture()
def traces_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """وجّه مجلد الجلسات إلى tmp — مع عزل عن أي NEXUS_TRACES_DIR سابق."""
    monkeypatch.setenv("NEXUS_TRACES_DIR", str(tmp_path))
    return tmp_path


def _make_session(home: Path, steps: int = 3) -> str:
    tracer = DeepTracer(session_dir=home)
    with tracer.session():
        tid = tracer.trace_id
        for i in range(steps):
            with tracer.span(f"step-{i}", agent="council",
                             attributes={"i": i}):
                pass
    return tid


# ───────────────────────── /api/traces/sessions ─────────────────────────


def test_sessions_empty_returns_ok(traces_home: Path) -> None:
    r = client.get("/api/traces/sessions")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["sessions"] == []


def test_sessions_lists_created_session(traces_home: Path) -> None:
    tid = _make_session(traces_home)
    r = client.get("/api/traces/sessions")
    body = r.json()
    assert body["ok"] is True
    ids = [s["session_id"] for s in body["sessions"]]
    assert tid in ids
    entry = body["sessions"][0]
    assert {"session_id", "ts", "bytes"} <= set(entry)


# ───────────────────────── /api/traces/{session_id} ─────────────────────


def test_replay_returns_ordered_steps(traces_home: Path) -> None:
    tid = _make_session(traces_home, steps=4)
    r = client.get(f"/api/traces/{tid}")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["count"] == 4
    names = [s["name"] for s in body["steps"]]
    assert names == ["step-0", "step-1", "step-2", "step-3"]
    # المتتالية على مستوى الجلسة: كلها جذور بلا أب.
    assert all(s["parent_span_id"] == "" for s in body["steps"])


def test_replay_preserves_nesting(traces_home: Path) -> None:
    tracer = DeepTracer(session_dir=traces_home)
    with tracer.session():
        tid = tracer.trace_id
        with tracer.span("outer") as outer:
            with tracer.span("inner"):
                pass
    body = client.get(f"/api/traces/{tid}").json()
    steps = body["steps"]
    assert steps[0]["name"] == "outer" and steps[1]["name"] == "inner"
    assert steps[1]["parent_span_id"] == outer.span_id


def test_replay_rejects_non_hex_session_id(traces_home: Path) -> None:
    r = client.get("/api/traces/not-a-valid-hex-id")
    assert r.status_code == 400


def test_replay_rejects_path_traversal(traces_home: Path) -> None:
    # 32 حرفًا لكن ليست hex — النقطة والشرطة لا يعبران بوابة الفحص.
    r = client.get("/api/traces/" + "a" * 31 + "g")
    assert r.status_code == 400


def test_replay_unknown_but_valid_id_is_404(traces_home: Path) -> None:
    r = client.get("/api/traces/" + "0" * 32)
    assert r.status_code == 404


def test_deliberate_response_includes_trace_session(
    traces_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """مداولة المجلس تُرجع trace_session قابلاً للفتح فورًا في replay."""

    class FakeResult:
        verdict = "ok"
        score = 0.9
        rounds = 1
        consensus = 0.8
        elapsed = 0.01
        transcript: list[dict[str, Any]] = [
            {"phase": "intro", "member": "analyst", "response": "r"}]
        security_events: list[str] = []

    class FakeEngine:
        MAX_ROUNDS = 3

        def deliberate_with_memory(self, question: str) -> FakeResult:
            return FakeResult()

    class FakeBridge:
        engine = FakeEngine()

        def deliberate_with_memory(self, question: str) -> FakeResult:
            return FakeResult()

    monkeypatch.setattr(
        "src.council.rag_bridge.get_council_bridge",
        lambda: FakeBridge(),
    )
    r = client.post("/api/council/deliberate",
                    json={"question": "سؤال اختبار؟"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    sid = body["trace_session"]
    assert len(sid) == 32
    # الجلسة نفسها مفتوحة عبر replay (تحقّق المستخدم النهائي).
    r2 = client.get(f"/api/traces/{sid}")
    assert r2.status_code == 200
    steps = r2.json()["steps"]
    assert [s["name"] for s in steps] == [
        "council.deliberate", "council.deliberate_with_memory"]
    # الشجرة: الابن معلّق بالأب، والسمات آمنة (لا نص سؤال المستخدم).
    assert steps[1]["parent_span_id"] == steps[0]["span_id"]
    assert "question" not in steps[0]["attributes"]
