"""Eval suite tests (M3.2) — hermetic: offline connector, isolated workdirs.

كل اختبار هنا بلا شبكة وبلا نموذج حقيقي: إما تحقق بنيوي في الكتالوج والحلول
المرجعية، أو تشغيل محرك كامل عبر OfflineConnector في مجلد عمل مؤقت.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.coder.plan import plan_from_json, validate
from src.evalsuite.__main__ import main
from src.evalsuite.offline import OfflineConnector, offline_factory
from src.evalsuite.report import (
    find_regressions,
    read_previous_records,
    summarize,
    write_report,
)
from src.evalsuite.runner import default_gate, prepare_workdir, run_suite, run_task
from src.evalsuite.tasks import (
    CATEGORIES,
    COUNTS,
    Task,
    by_category,
    catalog,
    get_task,
    plan_for,
)

# ───────────────────────────── الكتالوج ─────────────────────────────

def test_catalog_has_50_tasks_across_four_categories() -> None:
    tasks = catalog()
    assert len(tasks) == 50
    assert len({t.id for t in tasks}) == 50
    assert set(COUNTS) == set(CATEGORIES)
    for cat in CATEGORIES:
        assert len(by_category(cat)) == COUNTS[cat]


def test_every_task_is_wellformed() -> None:
    for t in catalog():
        assert t.goal.startswith(f"[{t.id}]"), t.id
        assert t.seed, t.id
        assert all(content.strip() for content in t.seed.values()), t.id
        paths = list(t.seed) + list(t.expect)
        assert all(not p.startswith("/") and ".." not in p for p in paths), t.id
        assert t.tests_to_run, t.id
        assert t.category in CATEGORIES, t.id


def test_every_reference_plan_is_valid_repair_plan() -> None:
    """The offline oracle must satisfy the very contract the engine enforces."""
    for t in catalog():
        plan = plan_from_json(plan_for(t))
        assert validate(plan) == [], t.id


def test_get_task_lookup_and_unknown() -> None:
    assert get_task("fix-03") is not None
    assert get_task("fix-03").category == "fix"
    assert get_task("nope-99") is None
    with pytest.raises(ValueError):
        by_category("bogus")


# ───────────────────────────── تشغيل e2e ─────────────────────────────

@pytest.mark.parametrize("task_id,expected_file", [
    ("create-01", "mod_01.py"),
    ("fix-01", "calc.py"),
    ("test-01", "test_lib_01.py"),
    ("docs-01", "README.md"),
])
async def test_offline_task_end_to_end(task_id: str,
                                       expected_file: str,
                                       tmp_path: Path) -> None:
    task = get_task(task_id)
    wd = tmp_path / task_id
    rec = await run_task(task, offline_factory(task), keep_workdir=wd)
    assert rec["ok"] is True, rec["reason"]
    assert rec["reason"] == "ok"
    assert (wd / expected_file).exists()
    assert rec["duration_ms"] >= 0


async def test_fix_task_solution_replaces_buggy_definition(tmp_path: Path) -> None:
    """ض6 (v1.58.0) edit semantics: unique find→replace — the buggy def is
    gone, not shadowed by an appended copy."""
    task = get_task("fix-01")
    wd = tmp_path / "fix"
    rec = await run_task(task, offline_factory(task), keep_workdir=wd)
    assert rec["ok"] is True, rec["reason"]
    text = (wd / "calc.py").read_text(encoding="utf-8")
    assert text.count("def calc(") == 1  # replaced in place, no shadow copy


class _BrokenPlan:
    """Detect passes, then every plan reply is unparseable JSON."""

    def __init__(self) -> None:
        self._calls = 0

    async def generate(self, prompt: str, system_prompt: str = "") -> dict:
        self._calls += 1
        if self._calls == 1:
            return {"ok": True, "reply": "[]"}
        return {"ok": True, "reply": "{goal: broken}"}


async def test_broken_model_task_fails_with_engine_reason(tmp_path: Path) -> None:
    rec = await run_task(get_task("create-02"), _BrokenPlan(),
                         keep_workdir=tmp_path, max_iterations=1)
    assert rec["ok"] is False
    assert rec["reason"].startswith("engine:")


async def test_offline_connector_exhaustion_is_reported(tmp_path: Path) -> None:
    conn = OfflineConnector(get_task("docs-01"))
    await conn.generate("p1")
    await conn.generate("p2")
    third = await conn.generate("p3")
    assert third == {"ok": False, "error": "offline script exhausted"}
    assert len(conn.calls) == 3


# ───────────────────────────── العدّاء والتقرير ─────────────────────────────

async def test_run_suite_limit_and_persistence(tmp_path: Path) -> None:
    out = tmp_path / "out"
    summary = await run_suite(offline_factory, limit=3, out_dir=out)
    assert summary["total"] == 3 and summary["ok"] == 3
    assert summary["ok_rate"] == 1.0
    assert summary["regressions"] == []
    records = read_previous_records(out)
    assert len(records) == 3 and all(r["ok"] is True for r in records)
    persisted = json.loads(
        (out / "evalsuite_summary.json").read_text(encoding="utf-8"))
    assert persisted["total"] == 3


async def test_run_suite_detects_regressions(tmp_path: Path) -> None:
    out = tmp_path / "out"
    await run_suite(offline_factory, task_id="create-01", out_dir=out)

    def broken_factory(task: Task) -> object:
        return _BrokenPlan()

    summary = await run_suite(broken_factory, task_id="create-01",
                              out_dir=out, max_iterations=1)
    assert summary["ok_rate"] == 0.0
    assert summary["regressions"] == ["create-01"]


async def test_unknown_task_id_raises() -> None:
    with pytest.raises(ValueError):
        await run_suite(offline_factory, task_id="ghost-01")


def test_summarize_rates_and_percentiles() -> None:
    records = [
        {"id": "a", "category": "create", "ok": True, "duration_ms": 100},
        {"id": "b", "category": "create", "ok": False, "duration_ms": 300},
        {"id": "c", "category": "fix", "ok": True, "duration_ms": 200},
        {"id": "d", "category": "fix", "ok": True},  # no duration recorded
    ]
    s = summarize(records)
    assert s["total"] == 4 and s["ok"] == 3 and s["ok_rate"] == 0.75
    assert s["by_category"]["create"] == {"total": 2, "ok": 1, "rate": 0.5}
    assert s["by_category"]["test"] == {"total": 0, "ok": 0, "rate": None}
    assert s["durations_ms"]["p50_ms"] == 200
    assert s["durations_ms"]["p95_ms"] == 300
    assert s["generated_at"]


def test_summarize_empty_is_all_none() -> None:
    s = summarize([])
    assert s["total"] == 0 and s["ok_rate"] is None
    assert s["durations_ms"]["p50_ms"] is None
    assert s["durations_ms"]["p95_ms"] is None


def test_find_regressions_and_previous_reading(tmp_path: Path) -> None:
    prev = [{"id": "x", "ok": True}, {"id": "y", "ok": False}]
    now = [{"id": "x", "ok": False}, {"id": "y", "ok": True}]
    assert find_regressions(now, prev) == ["x"]
    assert read_previous_records(tmp_path) == []
    write_report(tmp_path, prev, summarize(prev))
    assert read_previous_records(tmp_path) == prev


def test_previous_records_skip_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / "evalsuite.jsonl"
    path.write_text('{"id": "z", "ok": true}\nnot-json\n\n', encoding="utf-8")
    records = read_previous_records(tmp_path)
    assert len(records) == 1 and records[0]["id"] == "z"


def test_prepare_workdir_creates_nested_files(tmp_path: Path) -> None:
    task = Task(id="x-01", category="create", goal="[x-01] تجربة",
                seed={"a/b.py": "VALUE = 1\n"}, expect=("a/b.py",),
                solution_steps=())
    wd = tmp_path / "wd"
    prepare_workdir(task, wd)
    assert (wd / "a" / "b.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_default_gate_is_pytest_only() -> None:
    gate = default_gate()
    assert len(gate) == 1
    assert gate[0][-1] == "--maxfail=3"


# ───────────────────────────── واجهة CLI ─────────────────────────────

def test_cli_main_offline_run(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc = main(["--limit", "2", "--out", str(tmp_path / "out")])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total"] == 2 and data["ok_rate"] == 1.0


def test_cli_main_unknown_task_fails_closed(tmp_path: Path,
                                            capsys: pytest.CaptureFixture) -> None:
    rc = main(["--task", "ghost-99", "--out", str(tmp_path / "out")])
    assert rc == 1
    assert "ghost-99" in capsys.readouterr().err
