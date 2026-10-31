"""اختبارات سجل الأثر المعياري (Week-2): runs/trace.jsonl

العقد من خارطة المنتَجة: كل تشغيل وكيل/مجلس يكتب سطر JSON واحداً بالحقول
الإلزامية ts/agent/tool/duration_ms/outcome — والكتابة لا تُسقط التشغيل
المُتتبَّع أبداً. كل الاختبارات عزلية: NEXUS_TRACE_PATH يشير إلى tmp_path.
"""

from __future__ import annotations

import json
import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.observability import trace as trace_mod
from src.observability.trace import (
    REQUIRED_FIELDS,
    read_recent,
    trace_context,
    trace_event,
    trace_path,
)
from src.web import app as webapp
from src.web.app import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_trace(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """اعزل ملف الأثر لكل اختبار — لا كتابة في runs/ أثناء الاختبارات."""
    monkeypatch.setenv("NEXUS_TRACE_PATH", str(tmp_path / "trace.jsonl"))
    yield


def _read_lines(path: Any) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ───────────────────── عقد الحقول الإلزامية ─────────────────────

def test_event_writes_required_fields(tmp_path: Any) -> None:
    path = tmp_path / "trace.jsonl"
    ok = trace_event("code-reviewer", "run", outcome="ok", duration_ms=12.5)
    assert ok is True
    lines = _read_lines(path)
    assert len(lines) == 1
    ev = lines[0]
    for field in REQUIRED_FIELDS:                       # العقد: الخمسة دائماً
        assert field in ev, f"الحقل الإلزامي غائب: {field}"
    assert isinstance(ev["ts"], str) and "T" in ev["ts"]     # ISO-8601 UTC
    assert ev["ts"].endswith("+00:00") or ev["ts"].endswith("Z")
    assert ev["agent"] == "code-reviewer"
    assert ev["tool"] == "run"
    assert isinstance(ev["duration_ms"], (int, float)) and ev["duration_ms"] >= 0
    assert ev["outcome"] == "ok"


def test_event_without_duration_still_has_field(tmp_path: Any) -> None:
    trace_event("agent-x", "tool-y")
    ev = _read_lines(tmp_path / "trace.jsonl")[0]
    assert ev["duration_ms"] == 0.0                     # الحقل موجود دائماً
    assert ev["outcome"] == "ok"


def test_env_override_respected(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = tmp_path / "nested" / "custom.jsonl"
    monkeypatch.setenv("NEXUS_TRACE_PATH", str(custom))
    assert trace_path() == custom
    trace_event("a", "b")
    assert custom.exists() and len(_read_lines(custom)) == 1


def test_default_path_under_runs_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUS_TRACE_PATH", raising=False)
    p = trace_path()
    assert p.parent.name == "runs" and p.name == "trace.jsonl"
    assert p.parent.parent == trace_mod.ROOT            # داخل المستودع، مُتجاهَل في git


# ───────────────────── سياق التتبع ─────────────────────

def test_context_ok_measures_duration(tmp_path: Any) -> None:
    extra: dict[str, Any] = {}
    with trace_context("council", "deliberate", extra):
        extra["tool"] = "deliberate:rounds=1"
        extra["outcome"] = "ok"
    ev = _read_lines(tmp_path / "trace.jsonl")[0]
    assert ev["agent"] == "council"
    assert ev["tool"] == "deliberate:rounds=1"          # التعديل داخل الكتلة يُلتقط
    assert ev["outcome"] == "ok"
    assert ev["duration_ms"] >= 0


def test_context_error_records_and_reraises(tmp_path: Any) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        with trace_context("agent-x", "run"):
            raise RuntimeError("boom")
    ev = _read_lines(tmp_path / "trace.jsonl")[0]
    assert ev["outcome"] == "error"
    assert ev["error"] == "RuntimeError"                # النوع فقط — لا محتوى المستخدم
    assert "boom" not in json.dumps(ev)


def test_context_write_failure_never_breaks_body(
        tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """فشل التتبع (مجلد غير قابل للكتابة) لا يمنع الكتلة ولا استثناءها."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    monkeypatch.setenv("NEXUS_TRACE_PATH", str(blocker / "child" / "trace.jsonl"))
    with trace_context("a", "b"):
        pass                                            # النجاح رغم فشل الكتابة
    with pytest.raises(ValueError):
        with trace_context("a", "b"):
            raise ValueError("body still raises")


def test_extra_fields_truncated_no_none(tmp_path: Any) -> None:
    trace_event("a", "b", note="x" * 500, empty=None, count=3)
    ev = _read_lines(tmp_path / "trace.jsonl")[0]
    assert len(ev["note"]) == 200
    assert "empty" not in ev and ev["count"] == 3


# ───────────────────── الصمود: تزامن + تدوير ─────────────────────

def test_concurrent_writers_no_corruption(tmp_path: Any) -> None:
    threads, per_thread = 8, 25
    def worker(tid: int) -> None:
        for i in range(per_thread):
            trace_event(f"agent-{tid}", "run", outcome="ok", duration_ms=i)
    ts = [threading.Thread(target=worker, args=(t,)) for t in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    lines = _read_lines(tmp_path / "trace.jsonl")
    assert len(lines) == threads * per_thread           # لا سطر ضائع ولا مشوّه
    agents = {ev["agent"] for ev in lines}
    assert agents == {f"agent-{t}" for t in range(threads)}


def test_rotation_keeps_disk_bounded(
        tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "trace.jsonl"
    monkeypatch.setattr(trace_mod, "MAX_BYTES", 512)
    for i in range(40):
        trace_event("agent", "run", duration_ms=i, filler="y" * 40)
    assert path.exists() and path.stat().st_size < 512 * 2
    backup = path.with_name("trace.jsonl.1")
    assert backup.exists()                              # الدفعة الأولى دوُرت


def test_read_recent_ordering_and_limit(tmp_path: Any) -> None:
    for i in range(10):
        trace_event("agent", "run", duration_ms=i)
    events = read_recent(3)
    assert [e["duration_ms"] for e in events] == [7.0, 8.0, 9.0]   # الأحدث أخيراً
    assert read_recent(5) == read_recent(200)[-5:]      # حد أقصى 200 مقبول
    assert read_recent(0) == read_recent(-3) == [] or len(read_recent(1)) == 1


def test_read_recent_tolerates_missing_and_corrupt(tmp_path: Any) -> None:
    assert read_recent() == []                          # ملف غائب
    path = tmp_path / "trace.jsonl"
    path.write_text('{"ts":"t","agent":"a","tool":"b","duration_ms":1,"outcome":"ok"}\n'
                    "NOT-JSON{{{\n", encoding="utf-8")
    events = read_recent()
    assert len(events) == 1                             # السطر التالف يُتخطى بصمت


# ───────────────────── ربط نقاط النهاية (اختبار regression للعقد) ─────────────────────

def test_agent_run_endpoint_writes_trace(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """المسار: نقطة نهاية → trace_context → سطر متوافق مع العقد في الملف."""
    import nova.registry as reg_mod

    class _Echo:
        def run(self, prompt: str) -> str:
            return f"echo:{prompt}"

    class _Reg:
        def __len__(self) -> int:
            return 1

        def load_agent(self, name: str) -> Any:
            return _Echo()

    monkeypatch.setattr(reg_mod, "REGISTRY", _Reg())
    body = client.post("/api/agent/run",
                       json={"agent": "echo", "prompt": "hi", "use_rag": False}).json()
    assert body["ok"] is True
    ev = _read_lines(tmp_path / "trace.jsonl")[-1]
    for field in REQUIRED_FIELDS:
        assert field in ev
    assert ev["agent"] == "echo" and ev["tool"] == "run" and ev["outcome"] == "ok"


def test_agent_run_failure_traced_as_error(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    import nova.registry as reg_mod

    class _Boom:
        def run(self, prompt: str) -> str:
            raise RuntimeError("boom")

    class _Reg:
        def __len__(self) -> int:
            return 1

        def load_agent(self, name: str) -> Any:
            return _Boom()

    monkeypatch.setattr(reg_mod, "REGISTRY", _Reg())
    body = client.post("/api/agent/run",
                       json={"agent": "x", "prompt": "hi", "use_rag": False}).json()
    assert body["ok"] is False and "boom" in body["error"]
    ev = _read_lines(tmp_path / "trace.jsonl")[-1]
    assert ev["outcome"] == "error"                     # الفشل مُوثَّق في الأثر
    assert ev["agent"] == "x"


def test_council_endpoint_writes_trace(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    import src.council.rag_bridge as bridge_mod

    class _Result:
        verdict, score, rounds, consensus, elapsed = "approve", 0.9, 1, True, 0.01
        transcript: list[dict[str, Any]] = []
        security_events: list[str] = []

    class _Bridge:
        engine = type("E", (), {"MAX_ROUNDS": 3})()

        def deliberate_with_memory(self, q: str) -> _Result:
            return _Result()

    monkeypatch.setattr(bridge_mod, "get_council_bridge", lambda: _Bridge())
    body = client.post("/api/council/deliberate",
                       json={"question": "هل ندفع؟"}).json()
    assert body["ok"] is True and body["verdict"] == "approve"
    ev = _read_lines(tmp_path / "trace.jsonl")[-1]
    assert ev["agent"] == "council" and ev["tool"] == "deliberate"
    for field in REQUIRED_FIELDS:
        assert field in ev


def test_unknown_agent_http_400_traced(tmp_path: Any) -> None:
    """لا يوجد وكيل فعلي بهذا الاسم في REGISTRY الحقيقي → HTTPException 400."""
    body = client.post("/api/agent/run",
                       json={"agent": "does-not-exist-xyz", "prompt": "hi",
                             "use_rag": False}).json()
    assert body["ok"] is False
    ev = _read_lines(tmp_path / "trace.jsonl")[-1]
    assert ev["outcome"] == "error"


def test_trace_recent_endpoint(tmp_path: Any) -> None:
    trace_event("code-reviewer", "run", outcome="ok", duration_ms=1.0)
    r = client.get("/api/trace/recent", params={"limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and isinstance(body["events"], list)
    assert body["events"], "يجب أن يُرجع الحدث الذي كتبناه للتو"
    for field in REQUIRED_FIELDS:
        assert field in body["events"][-1]


def test_dashboard_page_renders_trace_section(tmp_path: Any) -> None:
    trace_event("supervisor", "run", outcome="ok", duration_ms=3.0)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "آخر أحداث الأثر" in r.text                  # القسم الجديد
    assert "<script" not in r.text.lower()              # قراءة-فقت: صفر JS
    assert "supervisor" in r.text and "3.0ms" in r.text


def test_dashboard_page_escapes_trace_content(tmp_path: Any) -> None:
    """وكيل باسم خبيث في ملف الأثر لا يجتاز Escape إلى الصفحة."""
    path = tmp_path / "trace.jsonl"
    payload = {"ts": "t", "agent": "<script>alert(1)</script>", "tool": "run",
               "duration_ms": 1, "outcome": "ok"}
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    r = client.get("/dashboard")
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text


def test_run_tracker_still_released_with_trace(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """التتبع لا يعطّل إطلاق خانة المهام الجارية (سلوك Week-1 يبقى سليماً)."""
    import nova.registry as reg_mod

    class _Echo:
        def run(self, prompt: str) -> str:
            return "ok"

    class _Reg:
        def __len__(self) -> int:
            return 1

        def load_agent(self, name: str) -> Any:
            return _Echo()

    monkeypatch.setattr(reg_mod, "REGISTRY", _Reg())
    before = client.get("/api/dashboard").json()["tasks_running"]
    client.post("/api/agent/run", json={"agent": "e", "prompt": "p", "use_rag": False})
    assert client.get("/api/dashboard").json()["tasks_running"] == before
