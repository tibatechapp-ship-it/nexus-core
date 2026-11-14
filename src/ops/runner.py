"""المجدول الموحّد — مهام مجدولة صامتة بمعزل فشل ومهلة قاسية لكل مهمة.

القواعد المعلنة المطبَّقة حرفيًا:

1. كل مهمة تُنفَّذ **بمعزل**: فشلها سجل وتقرير ولا يوقف بقية الدورة.
2. كل مهمة لها **مهلة قاسية** معلنة — المهمة المعلّقة تُعلَّم منتهية
   المهلة وتُكمل الدورة (الخيط المعطّق يُترك — حد بنيوي معلن
   لتنفيذ داخل العملية).
3. مخرجات الدورة تذهب إلى **ملخص واحد** لا إشعارات متفرقة.
4. ساعات صامتة تؤجّل دورة الصباح/المساء كاملة — لا جلب ليلي.

المهام المبنية جاهزةً (``build_default_jobs``): رصد صباح/مساء،
تقادم الفهرس، إغلاق التذاكر الخاملة، ملخص الدورة — كلها تعمل بلا
شبكة وبلا LLM، وحتمية المدخلات تعطي حتمية المخرجات.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any, Callable

from src.ops.indexer import OpsIndex
from src.ops.radar import OpsRadar, RadarResult
from src.ops.store import OpsStore
from src.ops.tickets import DEFAULT_STALE_DAYS, TicketBoard

__all__ = ["OpsJob", "CycleReport", "OpsRunner", "build_default_jobs"]

#: مهلة المهمة الافتراضية (ثوانٍ) — سقف معلن لكل مهمة.
DEFAULT_JOB_TIMEOUT = 60


@dataclass(frozen=True)
class OpsJob:
    """مهمة مجدولة واحدة — اسمها وفترتها ودالتها ومهلتها."""

    name: str
    func: Callable[[OpsStore], Any]
    cadence: str = "both"
    timeout_sec: int = DEFAULT_JOB_TIMEOUT

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("اسم المهمة فارغ")
        if self.cadence not in {"morning", "evening", "both"}:
            raise ValueError(f"فترة المهمة غير معروفة: {self.cadence!r}")
        if self.timeout_sec < 1:
            raise ValueError("مهلة المهمة لا تقل عن ثانية")


@dataclass
class JobOutcome:
    """نتيجة مهمة واحدة داخل دورة — الحالة والمدة والحمولة أو الخطأ."""

    name: str
    status: str  # ok | error | timeout
    seconds: float = 0.0
    payload: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """التمثيل القياسي للنتيجة — نص الخطأ مقصوص دائمًا."""
        return {
            "name": self.name, "status": self.status,
            "seconds": round(self.seconds, 3), "payload": self.payload,
            "error": self.error[:200],
        }


@dataclass
class CycleReport:
    """تقرير دورة كاملة — كل المهام بحالاتها ثم ما وُلّد من ملخصات."""

    cadence: str
    skipped_quiet: bool = False
    outcomes: list[JobOutcome] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """الدورة سليمة — لا فشل ولا انتهاء مهلة في أي مهمة."""
        return all(o.status == "ok" for o in self.outcomes)

    def to_dict(self) -> dict[str, Any]:
        """التمثيل القياسي للتقرير — يُخزَّن في ملخص الدورة كما هو."""
        return {
            "cadence": self.cadence, "skipped_quiet": self.skipped_quiet,
            "ok": self.ok, "jobs": [o.to_dict() for o in self.outcomes],
        }


class OpsRunner:
    """المجدول الموحّد — دورات صباح/مساء بمهام معزولة وملخص واحد."""

    def __init__(self, store: OpsStore, jobs: list[OpsJob],
                 quiet_hours: tuple[int, ...] = (0, 1, 2, 3, 4, 5),
                 max_workers: int = 2) -> None:
        self._store = store
        self._jobs = list(jobs)
        self._quiet = quiet_hours
        self._max_workers = max(1, max_workers)

    def run_cycle(self, cadence: str, now_hour: int | None = None) -> CycleReport:
        """دورة واحدة: مهام الفترة بمعزل ← تقرير ← ملخص مخزّن واحد."""
        if cadence not in {"morning", "evening"}:
            raise ValueError(f"الفترة غير معروفة: {cadence!r}")
        report = CycleReport(cadence=cadence)
        if now_hour is not None and now_hour in self._quiet:
            report.skipped_quiet = True
            self._store.audit("runner.skipped_quiet", cadence, {"hour": now_hour})
            return report
        due = [j for j in self._jobs if j.cadence in {cadence, "both"}]
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {pool.submit(self._run_job, j): j for j in due}
            for future, job in futures.items():
                report.outcomes.append(self._collect(future, job))
        self._store.add_digest(self._cycle_digest(report))
        return report

    def run_forever(self, interval_sec: int = 3600,
                    max_cycles: int | None = None) -> list[CycleReport]:
        """حلقة تشغيل صامتة — دورتان افتراضيًا في الاختبار، بلا نهاية فعليًا.

        ``max_cycles`` سقف اختباري معلن: ``None`` يعني حلقة لا نهائية
        في العملية الحية، وقيمة في الاختبار تُنهي الحلقة بسلام.
        """
        reports: list[CycleReport] = []
        cycles = 0
        while max_cycles is None or cycles < max_cycles:
            cadence = "morning" if cycles % 2 == 0 else "evening"
            reports.append(self.run_cycle(cadence))
            cycles += 1
            if max_cycles is None or cycles < max_cycles:
                time.sleep(interval_sec)
        return reports

    # ── تنفيذ مهمة واحدة ──────────────────────────────────────────────────

    def _run_job(self, job: OpsJob) -> Any:
        """تنفيذ الدالة — العزل يحدث هنا داخل المستقبل لا خارجه."""
        return job.func(self._store)

    def _collect(self, future: Any, job: OpsJob) -> JobOutcome:
        """جمع نتيجة مهمة — المهلة والفشل يُلتقطان ولا يمرّان للدورة."""
        t0 = time.monotonic()
        try:
            payload = future.result(timeout=job.timeout_sec)
        except FuturesTimeout:
            return JobOutcome(name=job.name, status="timeout",
                              seconds=time.monotonic() - t0,
                              error=f"تجاوزت المهلة {job.timeout_sec}ث")
        except Exception as exc:  # noqa: BLE001 — عزل الفشل مقصود هنا
            self._store.audit("runner.job_failed", job.name,
                              {"error": f"{type(exc).__name__}: {exc}"[:200]})
            return JobOutcome(name=job.name, status="error",
                              seconds=time.monotonic() - t0,
                              error=f"{type(exc).__name__}: {exc}"[:200])
        return JobOutcome(name=job.name, status="ok",
                          seconds=time.monotonic() - t0,
                          payload=payload if isinstance(payload, dict) else {})

    def _cycle_digest(self, report: CycleReport) -> Any:
        """ملخص الدورة — من كائن التقرير لا من إعادة القراءة."""
        from src.ops.contracts import Digest
        lines = [
            f"المهام: {len(report.outcomes)} — سليمة "
            f"{sum(1 for o in report.outcomes if o.status == 'ok')}",
        ]
        for o in report.outcomes:
            mark = {"ok": "✔", "error": "✘", "timeout": "⏱"}.get(o.status, "?")
            lines.append(f"{mark} {o.name}: {o.status} ({o.seconds:.2f}s)"
                         f"{' — ' + o.error if o.error else ''}")
        return Digest(
            kind="cycle", day=time.strftime("%Y-%m-%d"),
            payload={"report": report.to_dict(),
                     "summary": "\n".join(lines),
                     "counts": self._store.counts()},
        )


def build_default_jobs(radar: OpsRadar, index: OpsIndex,
                       board: TicketBoard,
                       stale_days: int = DEFAULT_STALE_DAYS) -> list[OpsJob]:
    """المهام الافتراضية الخمس — كلها بلا شبكة وبلا LLM وحتمية المدخلات.

    * ``radar_morning``/``radar_evening``: رصد كتالوغي (الجلب الحي
      خطّاف مُمرَّر عند التشغيل الفعلي لا هنا).
    * ``index_prune``: تقادم الشرائح المُنتهية.
    * ``tickets_autoclose``: إغلاق الخوامل بعد المدة المعلنة.
    * ``board_snapshot``: لقطة عدّية في كل دورة تدخل ملخصها.
    """

    def _radar(store: OpsStore) -> dict[str, Any]:
        cadence = "morning"
        result: RadarResult = radar.run(cadence)
        return {"radar": result.to_dict()}

    def _radar_evening(store: OpsStore) -> dict[str, Any]:
        result: RadarResult = radar.run("evening")
        return {"radar": result.to_dict()}

    def _prune(store: OpsStore) -> dict[str, Any]:
        return {"pruned": index.prune_expired()}

    def _autoclose(store: OpsStore) -> dict[str, Any]:
        return {"closed": board.auto_close_stale(stale_days)}

    def _snapshot(store: OpsStore) -> dict[str, Any]:
        return {"counts": store.counts(),
                "states": store.ticket_state_counts()}

    return [
        OpsJob("radar_morning", _radar, cadence="morning"),
        OpsJob("radar_evening", _radar_evening, cadence="evening"),
        OpsJob("index_prune", _prune, cadence="both"),
        OpsJob("tickets_autoclose", _autoclose, cadence="both"),
        OpsJob("board_snapshot", _snapshot, cadence="both"),
    ]
