"""Regression tests for scripts/benchmarks/run_benchmarks.py.

Covers the four pillars of the automated benchmarks (productization plan,
week 3 / nexus-core): the 20 standard tasks, the measurement core, the
regression gate (relative threshold + absolute floor + operational
success-rate enforcement) and the auto-generated Arabic report.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Callable

import pytest

_SCRIPT = (
    Path(__file__).resolve().parent.parent / "scripts" / "benchmarks" / "run_benchmarks.py"
)
_spec = importlib.util.spec_from_file_location("nexus_run_benchmarks", _SCRIPT)
assert _spec is not None and _spec.loader is not None
rb = importlib.util.module_from_spec(_spec)
# Register before exec: the script's @dataclass looks its module up in
# sys.modules during class construction.
sys.modules[_spec.name] = rb
_spec.loader.exec_module(rb)


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect every write path to tmp so tests never touch the repo tree."""
    monkeypatch.setenv("NEXUS_TRACE_PATH", str(tmp_path / "trace.jsonl"))
    monkeypatch.setattr(rb, "BASELINE_PATH", tmp_path / "baseline.json")
    monkeypatch.setattr(rb, "OUTPUT_PATH", tmp_path / "results.json")
    monkeypatch.setattr(rb, "DOC_PATH", tmp_path / "docs" / "benchmarks.md")
    monkeypatch.setattr(rb, "ITERATIONS", 5)


def _task_doc(
    p50_by_name: dict[str, float], rate: float = 1.0, iterations: int = 30
) -> dict[str, object]:
    """Craft a minimal results document for gate tests."""
    tasks = [
        {
            "name": name,
            "group": "اختبار",
            "description": "مهمة مصطنعة",
            "iterations": iterations,
            "p50_ms": p50,
            "p95_ms": p50 * 1.2,
            "mean_ms": p50,
            "max_ms": p50 * 1.5,
            "success_rate": rate,
        }
        for name, p50 in p50_by_name.items()
    ]
    return {
        "schema": rb.SCHEMA,
        "generated_at": "2026-11-01T00:00:00+00:00",
        "env": {"python": "3.12", "platform": "test", "machine": "x86_64",
                "iterations": iterations, "warmup": 3},
        "threshold_pct": rb.MAX_REGRESSION_PCT,
        "abs_floor_ms": rb.ABS_FLOOR_MS,
        "tasks": tasks,
    }


# ═══════════════════ المهام العشرون ═══════════════════
def test_build_tasks_is_twenty_unique_callable() -> None:
    tasks = rb.build_tasks()
    names = [t.name for t in tasks]
    assert len(tasks) == 20
    assert len(set(names)) == 20
    for t in tasks:
        assert t.group
        assert t.description
        assert isinstance(t.fn, Callable)  # type: ignore[arg-type]


def test_no_council_task_is_measured() -> None:
    # Honesty note: the council sleeps 0.3s/member by design — timing it
    # would measure sleep, not compute. It must stay out of the suite.
    names = [t.name for t in rb.build_tasks()]
    assert not any("council" in n for n in names)


def test_measure_success_and_stat_ordering() -> None:
    task = rb.BenchTask("x", "g", "d", lambda: 42)
    m = rb.measure(task, iterations=5, warmup=0)
    assert m["success_rate"] == 1.0
    assert m["iterations"] == 5
    assert m["p50_ms"] >= 0
    assert m["p95_ms"] >= m["p50_ms"]
    assert m["max_ms"] >= m["p95_ms"]


def test_measure_swallows_task_failure() -> None:
    def boom() -> None:
        raise RuntimeError("task exploded")

    task = rb.BenchTask("boom", "g", "d", boom)
    m = rb.measure(task, iterations=4, warmup=2)
    assert m["success_rate"] == 0.0
    assert m["iterations"] == 4


# ═══════════════════ بوابة الانحدار ═══════════════════
def test_regressions_flags_beyond_threshold() -> None:
    new = _task_doc({"task_a": 2.0})
    old = _task_doc({"task_a": 1.0})
    lines = rb.regressions(new, old)
    assert len(lines) == 1
    assert "task_a" in lines[0]
    assert "انحدار" in lines[0]


def test_regressions_ignores_within_threshold() -> None:
    assert rb.regressions(_task_doc({"a": 1.2}), _task_doc({"a": 1.0})) == []


def test_regressions_absolute_floor_ignores_micro_noise() -> None:
    # +300% but only +0.15ms — a shared-counter microsecond jitter, not a
    # real regression; the absolute floor exists exactly for this case.
    assert rb.regressions(_task_doc({"a": 0.2}), _task_doc({"a": 0.05})) == []


def test_regressions_ignores_unknown_and_zero_baseline() -> None:
    assert rb.regressions(_task_doc({"brand_new": 1.0}), _task_doc({})) == []
    assert rb.regressions(_task_doc({"a": 1.0}), _task_doc({"a": 0.0})) == []


def test_operational_failures_lists_partial_success() -> None:
    lines = rb.operational_failures(_task_doc({"a": 1.0}, rate=0.5, iterations=4))
    assert len(lines) == 1
    assert "2/4" in lines[0]
    assert "فشل تشغيلي" in lines[0]


def test_operational_failures_empty_when_all_ok() -> None:
    assert rb.operational_failures(_task_doc({"a": 1.0})) == []


# ═══════════════════ التقرير المولّد ═══════════════════
def test_render_md_sections_and_twenty_rows() -> None:
    doc = rb.run_all(3)
    md = rb.render_md(doc, "ملاحظة اختبار")
    assert "# 📊 قياسات الأداء المعيارية" in md
    assert "مُولَّد آلياً" in md
    assert "## الجدول" in md
    assert "| 20 |" in md
    assert "## ملاحظات صدق" in md
    assert "مجلس القرار" in md
    assert "## إعادة الإنتاج" in md
    assert "make benchmarks" in md
    assert "كل معدلات النجاح 100%" in md


def test_render_md_flags_failed_tasks_honestly() -> None:
    doc = _task_doc({"a": 1.0}, rate=0.5)
    md = rb.render_md(doc, "ملاحظة")
    assert "⚠ انخفض معدل النجاح" in md
    assert "كل معدلات النجاح 100%" not in md


# ═══════════════════ مسارات CLI ═══════════════════
def test_main_measure_generates_outputs(tmp_path: Path) -> None:
    assert rb.main([]) == 0
    results = json.loads(rb.OUTPUT_PATH.read_text(encoding="utf-8"))
    assert results["schema"] == rb.SCHEMA
    assert len(results["tasks"]) == 20
    doc = rb.DOC_PATH.read_text(encoding="utf-8")
    assert "قياسات الأداء المعيارية" in doc


def test_main_check_founding_mode_writes_candidate() -> None:
    assert rb.main(["--check"]) == 0
    candidate = rb.OUTPUT_PATH.parent / "baseline-candidate.json"
    assert candidate.exists()
    adopted = json.loads(candidate.read_text(encoding="utf-8"))
    assert len(adopted["tasks"]) == 20
    assert "لا خط أساس" in rb.DOC_PATH.read_text(encoding="utf-8")


def test_main_check_founding_rejects_failed_tasks(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = _task_doc({"a": 1.0}, rate=0.0)
    monkeypatch.setattr(rb, "run_all", lambda iterations: broken)
    assert rb.main(["--check"]) == 1
    assert "فشل تشغيلي" in capsys.readouterr().err


def test_main_check_gate_passes_on_identical_numbers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = _task_doc({"a": 1.0, "b": 0.5})
    rb.OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rb.OUTPUT_PATH.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    rb.BASELINE_PATH.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(rb, "run_all", lambda iterations: doc)
    assert rb.main(["--check"]) == 0


def test_main_check_gate_fails_on_regression(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = _task_doc({"slow_one": 2.0, "fast_one": 0.01})
    baseline = copy.deepcopy(doc)
    baseline_tasks = {t["name"]: t for t in baseline["tasks"]}  # type: ignore[index]
    baseline_tasks["slow_one"]["p50_ms"] = 0.2  # real 2.0 → +900% beyond any floor
    rb.BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    rb.BASELINE_PATH.write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(rb, "run_all", lambda iterations: doc)
    monkeypatch.setattr(rb, "ABS_FLOOR_MS", 0.0)
    assert rb.main(["--check"]) == 1
    assert "slow_one" in capsys.readouterr().err


def test_main_adopt_copies_candidate_and_renders_doc() -> None:
    # Founding mode (--check with no baseline) is what produces the candidate.
    assert rb.main(["--check"]) == 0
    candidate = rb.OUTPUT_PATH.parent / "baseline-candidate.json"
    assert rb.main(["--adopt", str(candidate)]) == 0
    baseline = json.loads(rb.BASELINE_PATH.read_text(encoding="utf-8"))
    assert baseline["schema"] == rb.SCHEMA
    doc = rb.DOC_PATH.read_text(encoding="utf-8")
    assert baseline["generated_at"][:10] in doc


def test_main_adopt_missing_file_exits_two(tmp_path: Path) -> None:
    assert rb.main(["--adopt", str(tmp_path / "nope.json")]) == 2


def test_gate_constants_match_documented_contract() -> None:
    # The plan and .env docs promise: >50% relative AND >0.2ms absolute.
    assert rb.MAX_REGRESSION_PCT == 50.0
    assert rb.ABS_FLOOR_MS == 0.2
    assert rb.WARMUP == 3
