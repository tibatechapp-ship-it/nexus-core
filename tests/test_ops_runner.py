"""اختبارات المجدول الموحّد واللوحة الواحدة — العزل والمهلة والحتمية."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from src.ops import OpsStore, OpsJob, OpsRunner
from src.ops.dashboard import OpsDashboard
from src.ops.indexer import OpsIndex
from src.ops.radar import OpsRadar
from src.ops.store import OpsStore as Store
from src.ops.tickets import TicketBoard


def _ok_job(store: Store) -> dict[str, Any]:
    """مهمة سليمة نموذجية — حمولة قاموسية."""
    return {"done": True}


def _fail_job(store: Store) -> dict[str, Any]:
    """مهمة فاشلة نموذجية — استثناء مقصود."""
    raise RuntimeError("انفجار مقصود")


def _sleep_job(store: Store) -> dict[str, Any]:
    """مهمة معلّقة — تتجاوز المهلة القصيرة في الاختبار."""
    time.sleep(2.0)
    return {}


class TestOpsJob:
    def test_invalid_job_rejected(self) -> None:
        """مهمة بلا اسم أو بفترة غريبة أو بمهلة صفرية رفع."""
        with pytest.raises(ValueError, match="اسم"):
            OpsJob("", _ok_job)
        with pytest.raises(ValueError, match="فترة"):
            OpsJob("x", _ok_job, cadence="hourly")
        with pytest.raises(ValueError, match="مهلة"):
            OpsJob("x", _ok_job, timeout_sec=0)


class TestOpsRunner:
    def _runner(self, store: Store, jobs: list[OpsJob]) -> OpsRunner:
        """مجدول بمهام الاختبار — عامل واحد للسرعة."""
        return OpsRunner(store, jobs, max_workers=1)

    def test_cycle_runs_due_jobs_and_isolates_failure(self) -> None:
        """فشل مهمة لا يوقف البقية — كل مهمة لها نتيجتها."""
        store = OpsStore(":memory:")
        jobs = [OpsJob("ok", _ok_job), OpsJob("boom", _fail_job)]
        report = self._runner(store, jobs).run_cycle("morning")
        statuses = {o.name: o.status for o in report.outcomes}
        assert statuses == {"ok": "ok", "boom": "error"}
        assert report.ok is False
        assert any(e["action"] == "runner.job_failed" for e in store.tail_audit(10))

    def test_timeout_marked_and_cycle_continues(self) -> None:
        """المهمة المعلّقة تُعلَّم منتهية المهلة والبقية تُكمل."""
        store = OpsStore(":memory:")
        jobs = [OpsJob("hang", _sleep_job, timeout_sec=1), OpsJob("ok", _ok_job)]
        report = self._runner(store, jobs).run_cycle("morning")
        statuses = {o.name: o.status for o in report.outcomes}
        assert statuses["hang"] == "timeout"
        assert statuses["ok"] == "ok"

    def test_cadence_filtering(self) -> None:
        """مهام الفترة وحدها تُنفَّذ — صباحية لا تعمل مساءً والعكس."""
        store = OpsStore(":memory:")
        jobs = [OpsJob("m", _ok_job, cadence="morning"),
                OpsJob("e", _ok_job, cadence="evening"),
                OpsJob("b", _ok_job, cadence="both")]
        morning = self._runner(store, jobs).run_cycle("morning")
        assert {o.name for o in morning.outcomes} == {"m", "b"}
        evening = self._runner(store, jobs).run_cycle("evening")
        assert {o.name for o in evening.outcomes} == {"e", "b"}

    def test_quiet_hour_skips_whole_cycle(self) -> None:
        """الساعة الصامتة تؤجل الدورة كاملة بعلم صريح وبلا مهام."""
        store = OpsStore(":memory:")
        report = self._runner(store, [OpsJob("x", _ok_job)]).run_cycle(
            "morning", now_hour=2
        )
        assert report.skipped_quiet and report.outcomes == []
        assert store.counts()["digests"] == 0

    def test_invalid_cadence_rejected(self) -> None:
        """فترة غير معروفة رفع — دورتان معلنتان فقط."""
        with pytest.raises(ValueError, match="الفترة"):
            self._runner(OpsStore(":memory:"), []).run_cycle("nightly")

    def test_cycle_digest_upserted_per_day(self) -> None:
        """ملخصا الدورتين في اليوم نفسه صف واحد — الملخص الواحد لا تراكم."""
        store = OpsStore(":memory:")
        self._runner(store, [OpsJob("x", _ok_job)]).run_cycle("morning")
        self._runner(store, [OpsJob("x", _ok_job)]).run_cycle("evening")
        assert store.counts()["digests"] == 1
        d = store.latest_digest("cycle")
        assert d is not None and "المهام" in d.payload["summary"]

    def test_non_dict_payload_recorded_empty(self) -> None:
        """حمولة غير قاموسية تُسجَّل فارغة — العقد قاموس لا شيء آخر."""
        store = OpsStore(":memory:")

        def _weird(store: Store) -> Any:
            return "نص وليس قاموسًا"

        report = self._runner(store, [OpsJob("w", _weird)]).run_cycle("morning")
        assert report.outcomes[0].status == "ok"
        assert report.outcomes[0].payload == {}

    def test_run_forever_max_cycles(self) -> None:
        """الحلقة المحدودة تنتهي بعد دورتي الصباح والمساء بالترتيب."""
        store = OpsStore(":memory:")
        reports = self._runner(store, [OpsJob("x", _ok_job)]).run_forever(
            interval_sec=0, max_cycles=2
        )
        assert [r.cadence for r in reports] == ["morning", "evening"]

    def test_default_jobs_execute(self) -> None:
        """المهام الافتراضية الخمس تعمل كاملة في دورة بلا شبكة."""
        store = OpsStore(":memory:")
        jobs = __import__("src.ops.runner", fromlist=["build_default_jobs"]) \
            .build_default_jobs(OpsRadar(store), OpsIndex(store), TicketBoard(store))
        report = OpsRunner(store, jobs, max_workers=1).run_cycle("morning")
        assert len(report.outcomes) == 4
        assert report.ok, str([o.to_dict() for o in report.outcomes])


class TestOpsDashboard:
    def test_snapshot_counts_and_gates(self) -> None:
        """اللقطة تجمع العدّ والحالات وأحدث ملخص — من المخزن الواحد."""
        store = OpsStore(":memory:")
        board = TicketBoard(store)
        board.open_ticket("radar", "أ")
        dash = OpsDashboard(store)
        snap = dash.snapshot()
        assert snap["counts"]["tickets"] == 1
        assert snap["ticket_states"] == {"open": 1}
        assert snap["latest_digest"] is None
        assert snap["failed_gates_total"] == 0

    def test_markdown_deterministic(self) -> None:
        """نفس المخزن ⇒ نفس النص حرفيًا — الحتمية مثبتة بمقارنة مضاعفة."""
        store = OpsStore(":memory:")
        board = TicketBoard(store)
        t = board.open_ticket("radar", "أول تذكرة")
        board.advance(t.id, "closed")
        OpsDashboard(store).build_cycle_digest()
        dash = OpsDashboard(store)
        text1 = dash.render_markdown()
        text2 = dash.render_markdown()
        assert text1 == text2
        assert "# لوحة الطبقة التشغيلية الداخلية" in text1
        assert "closed: 1" in text1

    def test_empty_store_markdown_honest(self) -> None:
        """المخزن الفارغ يعرض «لا ... بعد» — اللوحة لا تختلق."""
        text = OpsDashboard(OpsStore(":memory:")).render_markdown()
        assert "لا تذاكر بعد" in text and "لا ملخصات بعد" in text

    def test_write_files(self, tmp_path: Path) -> None:
        """الكتابة تنتج ملفين ثابتين ويمكن قراءتهما كـ JSON وMarkdown."""
        store = OpsStore(":memory:")
        OpsDashboard(store).build_cycle_digest()
        files = OpsDashboard(store, outdir=tmp_path / "out").write()
        assert files["markdown"].is_file() and files["json"].is_file()
        data = json.loads(files["json"].read_text(encoding="utf-8"))
        assert data["counts"]["digests"] == 1

    def test_failed_gates_counted(self) -> None:
        """البوابات الفاشلة تُعدّ في اللقطة — إشارة الحالة الصادقة."""
        from src.ops.contracts import GateResult
        store = OpsStore(":memory:")
        store.add_gate(GateResult(tool="webqa", target="/x", blocking=True,
                                  passed=False, findings=({"c": "html"},)))
        snap = OpsDashboard(store).snapshot()
        assert snap["failed_gates_total"] == 1

    def test_cycle_digest_includes_top_signals(self) -> None:
        """ملخص الدورة يعرض أعلى الإشارات — نص واحد لقناة واحدة."""
        from src.ops.contracts import Signal
        store = OpsStore(":memory:")
        store.add_signal(Signal(source="pypi", title="أداة وكلاء",
                                url="https://pypi.org/x", score=9.0))
        d = OpsDashboard(store).build_cycle_digest()
        assert "أداة وكلاء" in d.payload["summary"]
