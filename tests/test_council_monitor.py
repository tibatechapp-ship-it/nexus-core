"""Council monitor tests (ب1.4) — التقييم الحتمي من سجل الأثر.

العقد: قراءة-فقط من ``runs/trace.jsonl``، أرقام مطابقة لا تقريبات مبتكرة،
أحكام حتمية بقواعد معلنة، وغياب السجل ⇒ ``{}`` معلن.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.council.monitor import (
    CLEAR_MIN_RUNS,
    CLEAR_RATE,
    VERDICT_CLEAR,
    VERDICT_INSUFFICIENT,
    VERDICT_REVIEW,
    VERDICT_WATCH,
    WATCH_RATE,
    evaluate_agents,
    council_verdict,
    default_trace_path,
    summary,
)


def _row(agent: str, outcome: str = "ok", duration_ms: float = 10.0, tool: str = "run") -> str:
    return json.dumps({"ts": "2026-11-14T00:00:00Z", "agent": agent,
                       "tool": tool, "duration_ms": duration_ms,
                       "outcome": outcome})


@pytest.fixture()
def trace_file(tmp_path: Path) -> Path:
    return tmp_path / "trace.jsonl"


def test_evaluate_numbers_match_the_log(trace_file: Path) -> None:
    """الأرقام مطابقة حرفياً للسجل: معدل ومتوسط وآخر نتيجة لكل وكيل."""
    rows = [
        _row("coder", "ok", 100.0), _row("coder", "ok", 50.0),
        _row("coder", "fail", 200.0), _row("coder", "ok", 50.0),
    ]
    trace_file.write_text("\n".join(rows), encoding="utf-8")
    out = evaluate_agents(trace_file)
    assert set(out) == {"coder"}
    st = out["coder"]
    assert st["runs"] == 4 and st["ok"] == 3 and st["fail"] == 1
    assert st["success_rate"] == 0.75
    assert st["avg_ms"] == 100.0  # (100+50+200+50)/4
    assert st["last_outcome"] == "ok"


def test_grades_follow_the_declared_rules(trace_file: Path) -> None:
    """القواعد المعلنة: ≥0.95 و≥5 ⇒ clear؛ ≥0.8 ⇒ watch؛ أقل ⇒ review."""
    clear = [_row("a", "ok") for _ in range(CLEAR_MIN_RUNS)]        # 1.0
    watch = [_row("b", "ok")] * 4 + [_row("b", "fail")]             # 0.80
    review = [_row("c", "fail")] * 3 + [_row("c", "ok")] * 2        # 0.40
    trace_file.write_text("\n".join(clear + watch + review), encoding="utf-8")
    out = evaluate_agents(trace_file)
    assert out["a"]["grade"] == VERDICT_CLEAR
    assert out["b"]["grade"] == VERDICT_WATCH
    assert out["c"]["grade"] == VERDICT_REVIEW


def test_insufficient_data_is_declared_not_guessed(trace_file: Path) -> None:
    """أقل من الحد الأدنى ⇒ بلا حكم — البيئة الناقصة تُعلن لا تُخمَّن."""
    trace_file.write_text(_row("shy", "ok"), encoding="utf-8")
    out = evaluate_agents(trace_file)
    assert out["shy"]["grade"] == VERDICT_INSUFFICIENT
    assert out["shy"]["verdict"]["action"].startswith("لا حكم بعد")


def test_missing_trace_is_declared_empty(trace_file: Path) -> None:
    """غياب السجل ⇒ {} معلن — بلا قياس لا تقييم ولا انفجار."""
    assert evaluate_agents(trace_file) == {}
    assert evaluate_agents(default_trace_path().with_name("never-written.jsonl")) == {}


def test_corrupt_rows_are_dropped_silently(trace_file: Path) -> None:
    """السطر الفاسد يُسقط صامتاً — لا يهدم التقييم كله."""
    trace_file.write_text(
        "\n".join([_row("coder", "ok"), "{not json", "[]", "",
                   json.dumps({"ts": "x"})]),  # ts فقط بلا agent/outcome ⇒ يُسقط
        encoding="utf-8")
    out = evaluate_agents(trace_file)
    assert out["coder"]["runs"] == 1


def test_bad_duration_does_not_kill_the_row(trace_file: Path) -> None:
    """مدة فاسدة لا تُسقط الحدث — الحساب best-effort معلن."""
    trace_file.write_text(json.dumps({"ts": "t", "agent": "x", "tool": "run",
                                      "duration_ms": "abc", "outcome": "ok"}),
                          encoding="utf-8")
    out = evaluate_agents(trace_file)
    assert out["x"]["runs"] == 1 and out["x"]["avg_ms"] == 0.0


def test_verdicts_are_deterministic_with_evidence() -> None:
    """حكم المجلس يحمل دليله: الأرقام والعتبة في نص السبب."""
    review = {"grade": VERDICT_REVIEW, "success_rate": 0.40, "runs": 5}
    watch = {"grade": VERDICT_WATCH, "success_rate": 0.85, "runs": 10}
    clear = {"grade": VERDICT_CLEAR, "success_rate": 0.98, "runs": 20}
    assert "تدخل المجلس" in council_verdict(review)["action"]
    assert "0.4" in council_verdict(review)["reason"]
    assert "مراقبة مكثفة" in council_verdict(watch)["action"]
    assert "أداء سليم" in council_verdict(clear)["action"]


def test_summary_counts_by_grade(trace_file: Path) -> None:
    """الملخص عدّاد لكل درجة — للعرض الحي في الواجهة."""
    rows = ([_row("a", "ok")] * CLEAR_MIN_RUNS
            + [_row("b", "ok")] * 4 + [_row("b", "fail")])
    trace_file.write_text("\n".join(rows), encoding="utf-8")
    counts = summary(evaluate_agents(trace_file))
    assert counts[VERDICT_CLEAR] == 1
    assert counts[VERDICT_WATCH] == 1
    assert counts[VERDICT_REVIEW] == 0


def test_monitor_is_read_only(trace_file: Path) -> None:
    """المراقب لا يكتب شيئاً: الملف كما تركناه بحرفه وحجمه."""
    trace_file.write_text(_row("coder", "ok"), encoding="utf-8")
    before = trace_file.read_text(encoding="utf-8")
    evaluate_agents(trace_file)
    assert trace_file.read_text(encoding="utf-8") == before


def test_thresholds_are_the_declared_constants() -> None:
    """العتبات معلنة ولا تتغير خلفية: 0.95/0.80/5 — عقد الواجهة يعتمدها."""
    assert CLEAR_RATE == 0.95
    assert WATCH_RATE == 0.80
    assert CLEAR_MIN_RUNS == 5
