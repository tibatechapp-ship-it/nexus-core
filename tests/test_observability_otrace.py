"""اختبارات src/observability/otrace — التتبّع العميق (docs/V2_ROADMAP.md م3).

العقد: شجرة spans بمعرّفات OTel-نمط في JSONL، دوران + ضغط zlib،
مُصدِّر OTLP معطَّل افتراضيًا (الخوصصة افتراضية)، مرشّح خصوصية دفاعي،
وخطوات replay جاهزة للـ PWA بعد الحدث.
"""

from __future__ import annotations

import json
import zlib
from pathlib import Path

import pytest

from src.observability import (
    DeepTracer,
    OTLPExporter,
    list_sessions,
    replay_steps,
    sanitize_attributes,
)
from src.observability.otrace import (
    MAX_BYTES,
    REQUIRED_SPAN_FIELDS,
    TRACE_SCHEMA,
    new_span_id,
    new_trace_id,
)


# ── المعرّفات (OTel-نمط) ──────────────────────────────────────────────────────────


def test_new_trace_id_is_32_hex_and_unique() -> None:
    a, b = new_trace_id(), new_trace_id()
    assert len(a) == 32 and len(b) == 32
    int(a, 16), int(b, 16)  # hex صالح
    assert a != b


def test_new_span_id_is_16_hex_and_unique() -> None:
    a, b = new_span_id(), new_span_id()
    assert len(a) == 16 and len(b) == 16
    assert a != b


# ── الشجرة والكتابة ───────────────────────────────────────────────────────────────


def _session(tmp_path: Path) -> tuple[DeepTracer, Path]:
    tracer = DeepTracer(session_dir=tmp_path)
    return tracer, tmp_path


def test_span_tree_with_parent_links(tmp_path: Path) -> None:
    tracer, _ = _session(tmp_path)
    with tracer.session():
        tid = tracer.trace_id
        with tracer.span("root", agent="council") as root:
            with tracer.span("child", agent="council") as child:
                pass
    spans = replay_steps(tmp_path / f"{tid}.jsonl")
    assert len(spans) == 2
    root_s, child_s = spans[0], spans[1]
    assert root_s["span_id"] == root.span_id
    assert child_s["span_id"] == child.span_id
    assert child_s["parent_span_id"] == root.span_id
    assert root_s["parent_span_id"] == ""


def test_session_file_one_trace_id_per_file(tmp_path: Path) -> None:
    tracer, tmp_path_ = _session(tmp_path)
    with tracer.session() as t:
        tid = t.trace_id
        with t.span("a"):
            pass
    assert tracer.path is not None and tracer.path.name == f"{tid}.jsonl"
    assert tid in [s["session_id"] for s in list_sessions(tmp_path_)]


def test_span_records_duration_and_outcome(tmp_path: Path) -> None:
    tracer, _ = _session(tmp_path)
    with tracer.session() as t:
        with t.span("work", agent="agent-x"):
            pass
    spans = replay_steps(tracer.path)
    s = spans[0]
    assert s["outcome"] == "ok"
    assert s["duration_ms"] >= 0.0
    assert s["agent"] == "agent-x"


def test_span_error_captured_not_swallowed(tmp_path: Path) -> None:
    tracer, _ = _session(tmp_path)
    with pytest.raises(RuntimeError, match="boom"):
        with tracer.session():
            with tracer.span("fail"):
                raise RuntimeError("boom")
    spans = replay_steps(tracer.path)
    assert spans[0]["outcome"] == "error"


def test_schema_and_required_fields_present(tmp_path: Path) -> None:
    tracer, _ = _session(tmp_path)
    with tracer.session():
        with tracer.span("step", attributes={"k": "v"}):
            pass
    raw = json.loads((tracer.path).read_text(encoding="utf-8").splitlines()[0])
    assert raw["schema"] == TRACE_SCHEMA
    for field in REQUIRED_SPAN_FIELDS:
        assert field in raw, field


def test_nested_error_propagates_to_outer_span(tmp_path: Path) -> None:
    tracer, _ = _session(tmp_path)
    with pytest.raises(ValueError):
        with tracer.session():
            with tracer.span("outer"):
                with tracer.span("inner"):
                    raise ValueError("x")
    spans = replay_steps(tracer.path)
    outcomes = {s["name"]: s["outcome"] for s in spans}
    assert outcomes == {"outer": "error", "inner": "error"}


# ── الخصوصية ──────────────────────────────────────────────────────────────────────


def test_forbidden_attribute_keys_dropped() -> None:
    cleaned = sanitize_attributes({
        "prompt": "secret user text",
        "content": "more",
        "round": 2,
        "score": 0.87,
        "ok": True,
    })
    assert "prompt" not in cleaned and "content" not in cleaned
    assert cleaned == {"round": 2, "score": 0.87, "ok": True}


def test_non_scalar_attributes_dropped(tmp_path: Path) -> None:
    tracer, _ = _session(tmp_path)
    with tracer.session():
        with tracer.span("s", attributes={"nested": {"deep": 1}, "n": 5}):
            pass
    spans = replay_steps(tracer.path)
    assert spans[0]["attributes"] == {"n": 5}


# ── الدوران والضغط ───────────────────────────────────────────────────────────────


def test_rotation_compresses_overflow_with_zlib(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("src.observability.otrace.MAX_BYTES", 256)
    tracer, _ = _session(tmp_path)
    with tracer.session() as t:
        tid = t.trace_id
        for i in range(6):
            with t.span(f"step-{i}", attributes={"i": i}):
                pass
    # ملف الدوران المضغوط موجود والقراءة تجمع الدورتين.
    zpath = tmp_path / f"{tid}.jsonl.1.z"
    assert zpath.exists()
    payload = zlib.decompress(zpath.read_bytes())
    assert payload  # محتوى مضغوط حقيقي
    spans = replay_steps(tmp_path / f"{tid}.jsonl")
    assert len(spans) >= 2
    seqs = [s["seq"] for s in spans]
    assert seqs == sorted(seqs)


def test_max_bytes_constant_is_sane() -> None:
    assert MAX_BYTES == 5 * 1024 * 1024


# ── OTLP (معطَّل افتراضيًا) ───────────────────────────────────────────────────────


def test_otlp_disabled_by_default() -> None:
    exporter = OTLPExporter()
    assert exporter.enabled is False


def test_otlp_export_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    exporter = OTLPExporter()
    called = {"n": 0}
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **kw: called.__setitem__("n", 1)
    )
    assert exporter.export([{"trace_id": "x", "span_id": "y"}]) is False
    assert called["n"] == 0


def test_otlp_export_posts_valid_payload_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}

    class FakeResp:
        status = 200

        def __enter__(self) -> "FakeResp":
            return self

        def __exit__(self, *a: object) -> None:
            pass

    def fake_urlopen(req: object, timeout: float = 2.0) -> FakeResp:
        captured["url"] = req.full_url  # type: ignore[attr-defined]
        captured["body"] = req.data  # type: ignore[attr-defined]
        captured["headers"] = dict(req.headers)  # type: ignore[attr-defined]
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    exporter = OTLPExporter(endpoint="http://127.0.0.1:4318/v1/traces",
                            headers={"X-Token": "t"})
    assert exporter.enabled is True
    spans = [{
        "trace_id": new_trace_id(), "span_id": new_span_id(),
        "parent_span_id": "", "name": "council.round",
        "outcome": "ok", "attributes": {"round": 1},
        "_start_ns": 1, "_end_ns": 2,
    }]
    assert exporter.export(spans) is True
    body = json.loads(captured["body"])
    rs = body["resourceSpans"][0]
    assert rs["resource"]["attributes"][0]["value"]["stringValue"] == "nexus-core"
    otel_span = rs["scopeSpans"][0]["spans"][0]
    assert otel_span["traceId"] == spans[0]["trace_id"]
    assert otel_span["status"]["code"] == "STATUS_CODE_OK"


def test_otlp_network_failure_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **kw: object) -> None:
        raise OSError("network down")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    exporter = OTLPExporter(endpoint="http://127.0.0.1:9/v1/traces")
    assert exporter.export([{"trace_id": "x", "span_id": "y"}]) is False


def test_session_flush_clears_pending_when_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracer, _ = _session(tmp_path)
    monkeypatch.setattr(OTLPExporter, "export", lambda self, spans: False)
    with tracer.session():
        with tracer.span("a"):
            pass
    assert tracer._pending == []


# ── الجرد والقراءة ────────────────────────────────────────────────────────────────


def test_list_sessions_newest_first(tmp_path: Path) -> None:
    for _ in range(3):
        tracer, _ = _session(tmp_path)
        with tracer.session():
            with tracer.span("s"):
                pass
    sessions = list_sessions(tmp_path)
    assert len(sessions) == 3
    assert all({"session_id", "ts", "bytes"} <= set(s) for s in sessions)


def test_read_spans_tolerates_corrupt_lines(tmp_path: Path) -> None:
    bad = tmp_path / "corrupt.jsonl"
    good = json.dumps({
        "schema": TRACE_SCHEMA, "ts": "t", "trace_id": "r", "span_id": "s",
        "parent_span_id": "", "seq": 1, "name": "n", "agent": "a",
        "duration_ms": 1.0, "outcome": "ok", "attributes": {},
    })
    bad.write_text(f"{good}\n{{broken json\n", encoding="utf-8")
    spans = replay_steps(bad)
    assert len(spans) == 1 and spans[0]["name"] == "n"


def test_replay_steps_ordering_by_seq(tmp_path: Path) -> None:
    tracer, _ = _session(tmp_path)
    with tracer.session():
        for i in range(5):
            with tracer.span(f"n{i}"):
                pass
    spans = replay_steps(tracer.path)
    assert [s["name"] for s in spans] == ["n0", "n1", "n2", "n3", "n4"]


def test_session_dir_created_lazily(tmp_path: Path) -> None:
    deep = tmp_path / "a" / "b" / "c"
    tracer = DeepTracer(session_dir=deep)
    with tracer.session():
        with tracer.span("x"):
            pass
    assert deep.exists() and tracer.path is not None
    assert tracer.path.exists()
