"""Suite runner — isolates every task in its own workdir and runs the engine.

العدّاء (M3.2): يكتب بذور كل مهمة في مجلد عمل معزول جديد، يشغّل محرك المراحل
الخمس على المهمة بيوصل مُحقَن، يتحقق من الملفات المتوقعة، ويسجّل قيداً واحداً
لكل مهمة (ok/سبب/تكرارات/زمن). التشغيل تسلسلي عمداً — قرارات حتمية وقابل
لإعادة الإنتاج قبل أي توازٍ.
"""

from __future__ import annotations

import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.coder.engine import run_engine
from src.evalsuite import report as report_mod
from src.evalsuite.tasks import CATEGORIES, Task, by_category, catalog, get_task

#: بوابة التحقق الوحيدة داخل مجلد العمل — افتراضيات M3.1 تحتاج جذر مستودع
#: حقيقياً (check_annotations)، فجناح التقييم يمرر بوابة pytest صريحة.
def default_gate() -> list:
    """pytest over the (seeded) workdir — verifier tests define success."""
    return [[sys.executable, "-m", "pytest", "-q", "--no-header", "--maxfail=3"]]


def prepare_workdir(task: Task, workdir: Path) -> None:
    """Write the task's seed files into a (fresh) workdir."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    for rel, content in task.seed.items():
        target = workdir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _missing_expect(task: Task, workdir: Path) -> list[str]:
    return [p for p in task.expect if not (Path(workdir) / p).exists()]


async def run_task(task: Task, connector: Any, *,
                   keep_workdir: Path | None = None,
                   max_iterations: int = 2, test_timeout: int = 90,
                   gates: list | None = None) -> dict:
    """Run one task end-to-end and return its JSON record.

    ``keep_workdir`` keeps the workspace for inspection (CLI mode); otherwise
    a private temp workdir is created and deleted with the task. The expected
    paths are checked BEFORE the temp dir vanishes.
    """
    started = time.monotonic()
    if keep_workdir is not None:
        wd = Path(keep_workdir)
        wd.mkdir(parents=True, exist_ok=True)
        result = await _execute(task, connector, wd, max_iterations,
                                test_timeout, gates)
        missing = _missing_expect(task, wd)
    else:
        with tempfile.TemporaryDirectory(prefix=f"eval-{task.id}-") as tmp:
            wd = Path(tmp)
            result = await _execute(task, connector, wd, max_iterations,
                                    test_timeout, gates)
            missing = _missing_expect(task, wd)
    iterations = int(result.get("iterations", 0) or 0)
    if result.get("ok") is True and not missing:
        ok, reason = True, "ok"
    elif result.get("ok") is True:
        ok = False
        reason = "expect_missing: " + ", ".join(missing)
    else:
        ok = False
        reason = f"engine: {str(result.get('error', 'unknown'))[:200]}"
    return {
        "id": task.id,
        "category": task.category,
        "ok": ok,
        "reason": reason,
        "iterations": iterations,
        "duration_ms": round((time.monotonic() - started) * 1000, 2),
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


async def _execute(task: Task, connector: Any, wd: Path, max_iterations: int,
                   test_timeout: int, gates: list | None) -> dict:
    """Seed the workdir, then run the engine over it."""
    prepare_workdir(task, wd)
    result: dict = await run_engine(
        task.goal, connector, root=wd, workdir=wd,
        max_iterations=max_iterations,
        gates=gates if gates is not None else default_gate(),
        test_timeout=test_timeout,
    )
    return result


def _select(tasks: tuple | None, category: str | None, task_id: str | None,
            limit: int | None) -> tuple:
    if task_id:
        one = get_task(task_id)
        if one is None:
            raise ValueError(f"unknown task id: {task_id!r}")
        return (one,)
    if category:
        selected = by_category(category)
    else:
        selected = tasks if tasks is not None else catalog()
    if limit is not None:
        selected = selected[:limit]
    return selected


async def run_suite(connector_factory: Callable[[Task], Any], *,
                    tasks: tuple | None = None, category: str | None = None,
                    task_id: str | None = None, limit: int | None = None,
                    out_dir: Path | str | None = None,
                    max_iterations: int = 2,
                    test_timeout: int = 90) -> dict:
    """Run a selection of tasks and produce the automated report.

    ``connector_factory(task)`` builds a fresh connector per task (offline
    mode) or returns a shared one (real models). When ``out_dir`` is given,
    records and summary are persisted and regressions are diffed against the
    previous run found there.
    """
    selected = _select(tasks, category, task_id, limit)
    records: list = []
    for task in selected:
        rec = await run_task(task, connector_factory(task),
                             max_iterations=max_iterations,
                             test_timeout=test_timeout)
        records.append(rec)
    summary = report_mod.summarize(records)
    if out_dir is not None:
        out = Path(out_dir)
        previous = report_mod.read_previous_records(out)
        summary["regressions"] = report_mod.find_regressions(records, previous)
        report_mod.write_report(out, records, summary)
    else:
        summary["regressions"] = []
    return summary


def all_category_names() -> tuple[str, ...]:
    """Expose the category tuple without importing tasks at call sites."""
    return CATEGORIES
