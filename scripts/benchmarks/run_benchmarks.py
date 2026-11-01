#!/usr/bin/env python3
"""run_benchmarks.py — المولّد الآلي لـ ``docs/benchmarks.md`` (المعيار الرسمي للأداء).

Measures **20 standard tasks** against the offline framework surface
(``EchoBackend`` — no network, no live model) and produces:

* ``runs/benchmark-results.json``   — raw aggregates (p50/p95/mean/max, success rate)
* ``docs/benchmarks.md``            — the human-readable Arabic report (auto-generated)

**بوابة الانحدار**: مع ``--check`` تُقارن الوسيط (p50) لكل مهمة ضد
``benchmarks/baseline.json``؛ أي انحدار > ``NEXUS_BENCH_MAX_REGRESSION_PCT`` (افتراضي 50%)
**و**فارق مطلق > 0.2ms يُخرج برموز خروج 1 — حتى لا يُسقط أزيز عدّاد مشترك
ميكروثانيةً واحدة. مهمة بلا خط أساس بعد → «وضع التأسيس»: يُكتب مرشّح خط أساس
في ``runs/baseline-candidate.json`` ويُخرج 0 (يُعتمد يدوياً بـ ``--adopt``).

ملاحظة صدق: مجلس القرار (``CouncilEngine.deliberate``) خارج القياس عمداً —
ينام 0.3s لكل عضو بتصميمه، فقياسه يقيس النوم لا الحساب.

Stdlib only (convention). Usage::

    python3 scripts/benchmarks/run_benchmarks.py            # قياس + توليد التقرير
    python3 scripts/benchmarks/run_benchmarks.py --check    # + بوابة الانحدار
    python3 scripts/benchmarks/run_benchmarks.py --adopt runs/baseline-candidate.json
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.agents import all_agents  # noqa: E402
from src.agents.analyst import AnalystAgent  # noqa: E402
from src.agents.coder import CoderAgent  # noqa: E402
from src.agents.designer import DesignerAgent  # noqa: E402
from src.agents.devops import DevOpsAgent  # noqa: E402
from src.agents.planner import PlannerAgent  # noqa: E402
from src.agents.researcher import ResearcherAgent  # noqa: E402
from src.agents.reviewer import ReviewerAgent  # noqa: E402
from src.agents.security_auditor import SecurityAuditorAgent  # noqa: E402
from src.core.backend import EchoBackend  # noqa: E402
from src.core.model_router import ModelRouter, ModelTier  # noqa: E402
from src.core.types import Message  # noqa: E402
from src.observability.trace import read_recent, trace_context, trace_event  # noqa: E402
from src.orchestrator.decomposer import decompose  # noqa: E402
from src.patterns.pipeline import Pipeline  # noqa: E402
from src.tui.state import TuiState  # noqa: E402

SCHEMA = "nexus-benchmarks/v1"
BASELINE_PATH = Path(
    os.environ.get("NEXUS_BENCH_BASELINE", str(REPO_ROOT / "benchmarks" / "baseline.json"))
)
OUTPUT_PATH = Path(
    os.environ.get("NEXUS_BENCH_OUTPUT", str(REPO_ROOT / "runs" / "benchmark-results.json"))
)
DOC_PATH = Path(os.environ.get("NEXUS_BENCH_DOC", str(REPO_ROOT / "docs" / "benchmarks.md")))
ITERATIONS = int(os.environ.get("NEXUS_BENCH_ITERATIONS", "30"))
MAX_REGRESSION_PCT = float(os.environ.get("NEXUS_BENCH_MAX_REGRESSION_PCT", "50"))
ABS_FLOOR_MS = 0.2
WARMUP = 3
# العبارة الموحدة التي تُمرَّر لكل وكيل في مهام التشغيل — أساس القياس مشترك عمداً
PROMPT = "benchmark task"


# ═══════════════════ المهام المعيارية العشرون ═══════════════════
@dataclass(frozen=True)
class BenchTask:
    """One standard task: a name, an Arabic description, and the measured callable."""

    name: str
    group: str
    description: str
    fn: Callable[[], object]


def build_tasks() -> list[BenchTask]:
    """Assemble the 20 standard tasks on fresh offline fixtures."""
    backend = EchoBackend()
    agents = {
        "coder": CoderAgent(backend),
        "reviewer": ReviewerAgent(backend),
        "planner": PlannerAgent(backend),
        "analyst": AnalystAgent(backend),
        "researcher": ResearcherAgent(backend),
        "security": SecurityAuditorAgent(backend),
        "designer": DesignerAgent(backend),
        "devops": DevOpsAgent(backend),
    }
    tui = TuiState(backend=backend)
    registry = tui.registry
    pipeline = Pipeline(
        [
            agents["coder"],
            agents["reviewer"],
            agents["planner"],
            agents["analyst"],
        ]
    )
    messages = [
        Message(role="system", content="You are the Coder agent."),
        Message(role="user", content="اكتب دالة جمع رقمين."),
    ]

    def registry_lookup_cycle() -> int:
        """Names + fetch for each of the 20 registered agents."""
        names = registry.names()
        for name in names:
            registry.get(name)
        return len(names)

    tasks: list[BenchTask] = [
        # ── الوكلاء الثمانية (زمن استجابة وكيل واحد) ──
        BenchTask(
            "agent_run_coder",
            "الوكلاء",
            "تشغيل وكيل Coder على EchoBackend",
            lambda: agents["coder"].run(PROMPT),
        ),
        BenchTask(
            "agent_run_reviewer",
            "الوكلاء",
            "تشغيل وكيل Reviewer",
            lambda: agents["reviewer"].run(PROMPT),
        ),
        BenchTask(
            "agent_run_planner",
            "الوكلاء",
            "تشغيل وكيل Planner",
            lambda: agents["planner"].run(PROMPT),
        ),
        BenchTask(
            "agent_run_analyst",
            "الوكلاء",
            "تشغيل وكيل Analyst",
            lambda: agents["analyst"].run(PROMPT),
        ),
        BenchTask(
            "agent_run_researcher",
            "الوكلاء",
            "تشغيل وكيل Researcher",
            lambda: agents["researcher"].run(PROMPT),
        ),
        BenchTask(
            "agent_run_security",
            "الوكلاء",
            "تشغيل وكيل SecurityAuditor",
            lambda: agents["security"].run(PROMPT),
        ),
        BenchTask(
            "agent_run_designer",
            "الوكلاء",
            "تشغيل وكيل Designer",
            lambda: agents["designer"].run(PROMPT),
        ),
        BenchTask(
            "agent_run_devops",
            "الوكلاء",
            "تشغيل وكيل DevOps",
            lambda: agents["devops"].run(PROMPT),
        ),
        # ── الأنماط والتسجيل ──
        BenchTask(
            "team_build_all20",
            "الأنماط",
            "بناء فريق الوكلاء العشرين كاملاً",
            lambda: all_agents(backend),
        ),
        BenchTask(
            "pipeline_four_stage",
            "الأنماط",
            "خط أنابيب رباعي: Coder→Reviewer→Planner→Analyst",
            lambda: pipeline.run("benchmark chain"),
        ),
        BenchTask(
            "registry_lookup_cycle",
            "التسجيل",
            "جولة تسجيل كاملة: أسماء + جلب كل وكيل من العشرين",
            registry_lookup_cycle,
        ),
        BenchTask(
            "tui_run_agent",
            "التسجيل",
            "تشغيل عبر حالة الواجهة TuiState.run_agent (تسجيل كامل)",
            lambda: tui.run_agent("coder", PROMPT),
        ),
        # ── التوجيه والتفكيك ──
        BenchTask(
            "router_route_default",
            "التوجيه",
            "قرار توجيه افتراضي (تقدير تعقيد داخلي)",
            lambda: ModelRouter().route("refactor the concurrency layer"),
        ),
        BenchTask(
            "router_route_forced_tier",
            "التوجيه",
            "قرار توجيه بطبقة مفروضة POWERFUL",
            lambda: ModelRouter().route("say hello", tier=ModelTier.POWERFUL),
        ),
        BenchTask(
            "router_estimate_complexity",
            "التوجيه",
            "تقدير تعقيد مهمة",
            lambda: ModelRouter.estimate_complexity("refactor the concurrency layer"),
        ),
        BenchTask(
            "decompose_request",
            "التوجيه",
            "تفكيك طلب متعدد البنود إلى مهام فرعية",
            lambda: decompose("صمّم المعمارية وبرمج الوحدة واختبر التكامل ووثّق النتيجة"),
        ),
        # ── سجل الأثر ──
        BenchTask(
            "trace_event_write",
            "سجل الأثر",
            "كتابة حدث أثر واحد JSONL (خيط-آمن، best-effort)",
            lambda: trace_event(agent="benchmark", tool="task", duration_ms=0.1),
        ),
        BenchTask(
            "trace_read_recent",
            "سجل الأثر",
            "قراءة آخر 20 حدث أثر",
            lambda: read_recent(20),
        ),
        BenchTask(
            "trace_context_scope",
            "سجل الأثر",
            "نطاق trace_context كامل (توقيت + كتابة تلقائية)",
            _trace_scope,
        ),
        # ── البنية التحتية ──
        BenchTask(
            "backend_echo_generate",
            "البنية التحتية",
            "توليد EchoBackend الخالص (أرضية القياس الدنيا)",
            lambda: backend.generate(messages),
        ),
    ]
    return tasks


def _trace_scope() -> bool:
    with trace_context(agent="benchmark", tool="scope"):
        pass
    return True


# ═══════════════════ القياس ═══════════════════
def measure(task: BenchTask, iterations: int, warmup: int) -> dict[str, object]:
    """Run one task ``iterations`` times; never let a task failure escape."""
    for _ in range(warmup):
        try:
            task.fn()
        except Exception:  # noqa: BLE001 — warm-up failure surfaces as success_rate below
            pass
    durations: list[float] = []
    oks = 0
    for _ in range(iterations):
        started = perf_counter()
        ok = False
        try:
            task.fn()
            ok = True
        except Exception:  # noqa: BLE001 — counted as failure, never raised
            pass
        durations.append((perf_counter() - started) * 1000.0)
        if ok:
            oks += 1
    ordered = sorted(durations)
    p95_idx = max(0, min(len(ordered) - 1, int(round(0.95 * len(ordered))) - 1))
    return {
        "name": task.name,
        "group": task.group,
        "description": task.description,
        "iterations": iterations,
        "p50_ms": round(statistics.median(ordered), 4),
        "p95_ms": round(ordered[p95_idx], 4),
        "mean_ms": round(statistics.fmean(ordered), 4),
        "max_ms": round(ordered[-1], 4),
        "success_rate": round(oks / iterations, 4),
    }


def run_all(iterations: int) -> dict[str, object]:
    """Measure all 20 tasks and return the full results document."""
    tasks = build_tasks()
    results = [measure(t, iterations, WARMUP) for t in tasks]
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "env": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "iterations": iterations,
            "warmup": WARMUP,
        },
        "threshold_pct": MAX_REGRESSION_PCT,
        "abs_floor_ms": ABS_FLOOR_MS,
        "tasks": results,
    }


# ═══════════════════ بوابة الانحدار ═══════════════════
def regressions(results: dict[str, object], baseline: dict[str, object]) -> list[str]:
    """Return human-readable regression lines (new p50 vs baseline p50)."""
    base = {t["name"]: t for t in baseline.get("tasks", [])}  # type: ignore[union-attr]
    out: list[str] = []
    for task in results.get("tasks", []):  # type: ignore[union-attr]
        old = base.get(str(task["name"]))
        if old is None:
            continue
        new_p50 = float(task["p50_ms"])  # type: ignore[arg-type]
        old_p50 = float(old["p50_ms"])  # type: ignore[arg-type]
        if old_p50 <= 0:
            continue
        pct = (new_p50 - old_p50) / old_p50 * 100.0
        if pct > MAX_REGRESSION_PCT and (new_p50 - old_p50) > ABS_FLOOR_MS:
            out.append(
                f"انحدار {task['name']}: p50 {old_p50:.3f}ms → {new_p50:.3f}ms "
                f"(+{pct:.0f}% > عتبة {MAX_REGRESSION_PCT:.0f}%)"
            )
    return out


def operational_failures(results: dict[str, object]) -> list[str]:
    """Return lines for tasks that did not succeed 100% of their iterations.

    A timing number measured on failed calls is meaningless, so the gate
    treats a broken task as a failure in its own right — regardless of how
    fast (or slow) the few successful calls were.
    """
    out: list[str] = []
    for task in results.get("tasks", []):  # type: ignore[union-attr]
        rate = float(task["success_rate"])  # type: ignore[arg-type]
        if rate < 1.0:
            iters = int(task["iterations"])  # type: ignore[arg-type]
            oks = round(rate * iters)
            out.append(
                f"فشل تشغيلي {task['name']}: نجح {oks}/{iters} فقط — "
                "المهمة يجب أن تنجح كلياً قبل أي قياس زمني"
            )
    return out


# ═══════════════════ توليد التقرير ═══════════════════
def render_md(results: dict[str, object], baseline_note: str) -> str:
    """Render the Arabic auto-generated report (docs/benchmarks.md)."""
    env = results["env"]  # type: ignore[index]
    lines: list[str] = [
        "# 📊 قياسات الأداء المعيارية — nexus-core",
        "",
        "> **مُولَّد آلياً** بواسطة `scripts/benchmarks/run_benchmarks.py` — لا تُعدّله يدوياً؛",
        "> أعد التوليد بـ `make benchmarks`.",
        "",
        f"- **تاريخ القياس**: `{results['generated_at']}`",  # type: ignore[index]
        f"- **البيئة**: بايثون `{env['python']}` · `{env['machine']}` · {env['platform']}",  # type: ignore[index]
        f"- **المنهج**: {len(results['tasks'])} مهمة معيارية × {env['iterations']} تكراراً "  # type: ignore[index]
        f"(إحماء {env['warmup']}) على مسار `EchoBackend` الخالص — بلا شبكة ولا نموذج حي.",  # type: ignore[index]
        f"- **بوابة CI**: انحدار p50 > {MAX_REGRESSION_PCT:.0f}% **و**فارق مطلق > {ABS_FLOOR_MS}ms "
        "يسقط الوظيفة (`--check` ضد `benchmarks/baseline.json`).",
        f"- **مصدر الخط الأساسي**: {baseline_note}",
        "",
        "## الجدول",
        "",
        "| # | المهمة | المجموعة | p50 (ms) | p95 (ms) | معدل النجاح |",
        "|--:|---|---|--:|--:|--:|",
    ]
    for i, t in enumerate(results["tasks"], 1):  # type: ignore[union-attr]
        lines.append(
            f"| {i} | `{t['name']}` — {t['description']} | {t['group']} "
            f"| {t['p50_ms']:.3f} | {t['p95_ms']:.3f} | {t['success_rate']*100:.0f}% |"
        )
    slowest = max(results["tasks"], key=lambda t: float(t["p50_ms"]))  # type: ignore[arg-type,index]
    failures = operational_failures(results)
    if failures:
        rate_line = (
            f"⚠ انخفض معدل النجاح في {len(failures)} مهمة — انظر عمود معدل النجاح؛ "
            "بوابة CI تسقط هذا القياس حتى لو كان زمنه مقبولاً."
        )
    else:
        rate_line = "وأسرعها بمرتبات الميكروثانية؛ كل معدلات النجاح 100%."
    lines += [
        "",
        f"**أبطأ مهمة**: `{slowest['name']}` عند {slowest['p50_ms']:.3f}ms — {rate_line}",
        "",
        "## ملاحظات صدق",
        "",
        "- مجلس القرار (`CouncilEngine.deliberate`) **خارج القياس عمداً**: ينام 0.3s لكل عضو "
        "بتصميمه (إيقاع مداولة بشري)، فقياسه الزمني يقيس النوم لا الحساب.",
        "- قياسات CI تعمل على عدّادات مشتركة؛ لذلك البوابة نسبية (وسيط 30 عينة) مع أرضية "
        f"مطلقة {ABS_FLOOR_MS}ms تمنع إسقاطات الأزيز على مهام الميكروثانية.",
        "- القياسات تقيس **إطار العمل** (تجميع، توجيه، تتبع) لا استدعاء نموذج حي — "
        "قياس النماذج الحية أداة مستقلة سابقة (`scripts/benchmark/` مقابل بوابة مشغّلة).",
        "",
        "## إعادة الإنتاج",
        "",
        "```bash",
        "make benchmarks          # قياس كامل + توليد هذا الملف",
        "make benchmarks-check    # نفس القياس + بوابة الانحدار ضد الخط الأساسي",
        "# اعتماد خط أساس جديد (بعد تنزيله من artifact الـCI أو من قياس محلي مدروس):",
        "python3 scripts/benchmarks/run_benchmarks.py --adopt runs/baseline-candidate.json",
        "```",
        "",
    ]
    return "\n".join(lines)


def write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ═══════════════════ CLI ═══════════════════
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="nexus-core standard benchmarks (20 tasks)")
    parser.add_argument("--check", action="store_true", help="compare vs baseline; exit 1 on regression")
    parser.add_argument(
        "--adopt", metavar="JSON", help="copy a candidate baseline into benchmarks/baseline.json"
    )
    parser.add_argument("--quiet", action="store_true", help="suppress progress lines")
    args = parser.parse_args(argv)

    def say(msg: str) -> None:
        if not args.quiet:
            print(msg)

    # 1) adoption path: copy candidate → baseline, regenerate doc from it, done.
    if args.adopt:
        src = Path(args.adopt)
        if not src.exists():
            print(f"✗ ملف الاعتماد غير موجود: {src}", file=sys.stderr)
            return 2
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, BASELINE_PATH)
        adopted = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        env = adopted.get("env", {})
        note = f"`{env.get('platform', 'غير موثق')}` (بايثون {env.get('python', '?')})"
        DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
        DOC_PATH.write_text(render_md(adopted, note), encoding="utf-8")
        say(f"✓ اعتُمد الخط الأساسي: {BASELINE_PATH} ({len(adopted.get('tasks', []))} مهمة)")
        say(f"✓ جُدّد التقرير من أرقام الخط: {DOC_PATH}")
        return 0

    # 2) measurement path
    say(f"⏱ قياس 20 مهمة معيارية × {ITERATIONS} تكراراً (إحماء {WARMUP})…")
    results = run_all(ITERATIONS)
    write_json(OUTPUT_PATH, results)
    say(f"✓ النتائج الخام: {OUTPUT_PATH}")

    baseline: dict[str, object] | None = None
    if BASELINE_PATH.exists():
        try:
            baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            baseline = None

    if args.check and baseline is None:
        # ── وضع التأسيس: لا خط أساس بعد → اكتب مرشحاً ولا تُسقط البوابة ──
        broken = operational_failures(results)
        if broken:
            print("\n".join(f"✗ {b}" for b in broken), file=sys.stderr)
            print(
                "\nوضع التأسيس لن يعتمد قياساً فيه مهام فاشلة — أصلح الأعطال أولاً.",
                file=sys.stderr,
            )
            return 1
        candidate = OUTPUT_PATH.parent / "baseline-candidate.json"
        write_json(candidate, results)
        DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
        DOC_PATH.write_text(
            render_md(results, "لا خط أساس معتمد بعد — الأرقام من هذا القياس (مرشح)"),
            encoding="utf-8",
        )
        say(f"⚠ وضع التأسيس: لا خط أساس في {BASELINE_PATH}")
        say(f"  كُتب مرشّح للاعتماد في: {candidate} (ثم --adopt بعد المراجعة)")
        return 0

    note = (
        f"`{baseline['env']['platform']}` (بايثون {baseline['env']['python']}, "
        f"{baseline['generated_at'][:10]})"  # type: ignore[index]
        if baseline
        else "غير معتمد"
    )
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(render_md(results, note), encoding="utf-8")
    say(f"✓ التقرير: {DOC_PATH}")

    if args.check and baseline is not None:
        bad = regressions(results, baseline) + operational_failures(results)
        if bad:
            print("\n".join(f"✗ {b}" for b in bad), file=sys.stderr)
            print(f"\nفشلت بوابة الانحدار: {len(bad)} ملاحظة تجاوزت العتبة.", file=sys.stderr)
            return 1
        say(f"✓ بوابة الانحدار: لا مهمة تجاوز {MAX_REGRESSION_PCT:.0f}% ضد الخط الأساسي، وكل المعدلات 100%.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
