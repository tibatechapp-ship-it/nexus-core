"""اختبار العرض الشامل — التحدي النهائي بمساره الأخضر والمرفوض.

هذا هو إثبات «منظمة هندسية» بلا شبكة ولا مفاتيح: هدف هندسي → خطة →
تطوير معزول → مراجعة مستقلة → اختبارات داخل العزل → تحقق بالأدلة →
تقرير وتذكرة ببوابة دمج بشرية. كل ناتج من متجر حتمي قابل للتدقيق.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.org.dashboard import OrgDashboard
from src.org.learning import LessonsEngine
from src.org.metrics import OrgMetrics
from src.org.pipeline import MissionPipeline
from src.org.providers import MockProvider, ProviderConfig, ProviderPool
from src.org.store import OrgStore
from src.ops.store import OpsStore

OBJECTIVE = ("أضف حارس قسمة على صفر إلى دالة divide في وحدة calc.mathops "
             "مع اختبارات للحدية")
LOCAL_EXECUTION_POLICY = {
    "schema_version": 1, "execution_mode": "process", "trusted_local": True,
}


def _patched_pool(provider_cls: type[MockProvider]) -> ProviderPool:
    pool = ProviderPool([ProviderConfig()])
    original_get = pool.get

    def patched_get(name: str = "", model: str = "") -> object:
        prov = original_get(name, model)
        if isinstance(prov, MockProvider):
            prov.__class__ = provider_cls
        return prov

    pool.get = patched_get  # type: ignore[method-assign]
    return pool


class TestGreenPath:
    def test_pipeline_requires_explicit_execution_policy(
            self, tmp_path: Path) -> None:
        pipeline = MissionPipeline(
            OrgStore(":memory:"), OpsStore(":memory:"),
            outdir=tmp_path / "missing-policy",
        )
        with pytest.raises(ValueError, match="execution_policy is required"):
            pipeline.run(
                title="must fail closed", objective="do not infer trust",
                repo_path="examples/org_demo/fixture_repo",
            )

    @pytest.fixture()
    def report(self, tmp_path: Path) -> object:
        org = OrgStore(":memory:")
        ops = OpsStore(":memory:")
        pipeline = MissionPipeline(org, ops, outdir=tmp_path / "reports")
        return pipeline.run(title="حارس قسمة على صفر", objective=OBJECTIVE,
                            repo_path="examples/org_demo/fixture_repo",
                            execution_policy=LOCAL_EXECUTION_POLICY)

    def test_mission_done_at_release(self, report: object) -> None:
        assert report.mission.status == "done"  # type: ignore[attr-defined]
        assert report.mission.phase == "G_RELEASE"  # type: ignore[attr-defined]

    def test_all_tasks_done(self, report: object) -> None:
        assert report.metrics["completion_rate"] == 1.0  # type: ignore[attr-defined]
        assert report.metrics["verified_fix_rate"] == 1.0  # type: ignore[attr-defined]

    def test_ticket_and_approval_human_gate(self, report: object) -> None:
        assert report.ticket_id  # type: ignore[attr-defined]
        assert report.approval_id  # type: ignore[attr-defined]
        assert report.mission.status == "done"  # type: ignore[attr-defined]

    def test_artifacts_on_disk(self, report: object) -> None:
        assert Path(report.report_path).exists()  # type: ignore[attr-defined]
        assert Path(report.patch_path).exists()  # type: ignore[attr-defined]
        patch = Path(report.patch_path).read_text(encoding="utf-8")  # type: ignore[attr-defined]
        assert "calc/mathops.py" in patch

    def test_report_honesty_sections(self, report: object) -> None:
        text = Path(report.report_path).read_text(encoding="utf-8")  # type: ignore[attr-defined]
        assert "[verified]" in text
        assert "publish_allowed=False" in text
        assert "بوابة الدمج بشرية" in text

    def test_acceptance_criteria_stored(self, report: object) -> None:
        criteria = report.mission.acceptance_criteria  # type: ignore[attr-defined]
        assert criteria and any("صفر" in c for c in criteria)


class TestRejectedPaths:
    def test_broken_patch_rejected_at_verification(
            self, tmp_path: Path) -> None:
        """رقعة تعطّل الاختبارات لا تصل للإصدار إطلاقًا."""

        class BrokenDevProvider(MockProvider):
            def _dev_reply(self, prompt: str) -> str:
                import json
                base = json.loads(super()._dev_reply(prompt))
                for c in base["changed_files"]:
                    if "test" not in c["path"]:
                        c["content"] = (
                            "def divide(value, divisor):\n"
                            "    if divisor == 0:\n"
                            "        raise ValueError(\"صفر\")\n"
                            "    return value + divisor\n")
                return json.dumps(base, ensure_ascii=False)

        org = OrgStore(":memory:")
        ops = OpsStore(":memory:")
        pipeline = MissionPipeline(
            org, ops, pool=_patched_pool(BrokenDevProvider),
            outdir=tmp_path / "reports")
        report = pipeline.run(title="رقعة معطوبة", objective=OBJECTIVE,
                              repo_path="examples/org_demo/fixture_repo", execution_policy=LOCAL_EXECUTION_POLICY)
        assert report.mission.status == "failed"
        assert report.mission.phase == "FAILED"
        assert report.ticket_id == ""  # لا تذكرة لمهمة رفضها التحقق
        claims = {c.statement: c.status
                  for c in org.claims_for(report.mission.id)}
        assert any(status == "rejected" for status in claims.values())

    def test_todo_patch_rejected_at_review(self, tmp_path: Path) -> None:
        """رقعة بـTODO تُرفض مراجعةً وتُنهى المهمة بسقف الدورة."""

        class TodoDevProvider(MockProvider):
            def _dev_reply(self, prompt: str) -> str:
                import json
                base = json.loads(super()._dev_reply(prompt))
                for c in base["changed_files"]:
                    c["content"] += "\n# TODO: لاحقًا\n"
                return json.dumps(base, ensure_ascii=False)

        org = OrgStore(":memory:")
        ops = OpsStore(":memory:")
        pipeline = MissionPipeline(
            org, ops, pool=_patched_pool(TodoDevProvider),
            outdir=tmp_path / "reports")
        pipeline.run(title="رقعة متأجلة", objective=OBJECTIVE,
                     repo_path="examples/org_demo/fixture_repo", execution_policy=LOCAL_EXECUTION_POLICY)
        mission = org.mission_list()[0]
        assert mission.status == "failed"
        assert mission.revision_loops >= 1


class TestDeterminism:
    def test_two_runs_same_mission_id(self, tmp_path: Path) -> None:
        ids = []
        for i in range(2):
            org = OrgStore(":memory:")
            ops = OpsStore(":memory:")
            pipeline = MissionPipeline(org, ops,
                                       outdir=tmp_path / f"r{i}")
            report = pipeline.run(title="حارس قسمة على صفر",
                                  objective=OBJECTIVE,
                                  repo_path="examples/org_demo/fixture_repo", execution_policy=LOCAL_EXECUTION_POLICY)
            ids.append(report.mission.id)
        assert ids[0] == ids[1]

    def test_dashboard_deterministic_after_same_state(
            self, tmp_path: Path) -> None:
        """العقد الحتمي المعلن: نفس المخزن نفس نص التقرير حرفيًا.

        المقارنة بين تشغيلين مستقلين تشمل زمن استجابة حقيقيًا مقيسًا
        (observability صادق)، فالحتمية النصية الكاملة عقد المخزن الواحد.
        """
        org = OrgStore(":memory:")
        ops = OpsStore(":memory:")
        pipeline = MissionPipeline(org, ops, outdir=tmp_path / "d")
        pipeline.run(title="حارس قسمة على صفر", objective=OBJECTIVE,
                     repo_path="examples/org_demo/fixture_repo", execution_policy=LOCAL_EXECUTION_POLICY)
        dash = OrgDashboard(org, outdir=tmp_path / "d")
        assert dash.markdown_report() == dash.markdown_report()

    def test_dashboard_structure_stable_across_runs(
            self, tmp_path: Path) -> None:
        """بنية اللوحة ثابتة بين تشغيلين: الأعداد والمعدلات متطابقة."""
        import json

        snaps = []
        for i in range(2):
            org = OrgStore(":memory:")
            ops = OpsStore(":memory:")
            pipeline = MissionPipeline(org, ops,
                                       outdir=tmp_path / f"s{i}")
            pipeline.run(title="حارس قسمة على صفر", objective=OBJECTIVE,
                         repo_path="examples/org_demo/fixture_repo", execution_policy=LOCAL_EXECUTION_POLICY)
            snap = OrgDashboard(org, outdir=tmp_path / f"s{i}").snapshot()
            snap.pop("usage")  # زمن استجابة حقيقي مقيس — ليس عقدًا حتميًا
            snaps.append(json.dumps(snap, sort_keys=True))
        assert snaps[0] == snaps[1]
        # والأقسام المعلنة حاضرة دائمًا
        report = OrgDashboard(org, outdir=tmp_path).markdown_report()
        for section in ("## العدّادات", "## المعدلات", "## الاستهلاك",
                        "## الأنماط المتكررة", "## الدروس النشطة"):
            assert section in report


class TestObservability:
    def test_metrics_after_green_run(self, tmp_path: Path) -> None:
        org = OrgStore(":memory:")
        ops = OpsStore(":memory:")
        pipeline = MissionPipeline(org, ops, outdir=tmp_path / "m")
        report = pipeline.run(title="حارس قسمة", objective=OBJECTIVE,
                              repo_path="examples/org_demo/fixture_repo", execution_policy=LOCAL_EXECUTION_POLICY)
        assert report.mission.status == "done"
        metrics = OrgMetrics(org)
        snap = metrics.snapshot()
        assert snap["completion_rate"] == 1.0
        assert snap["usage"]["agent_runs"] > 0
        assert snap["usage"]["tokens_in"] > 0

    def test_lessons_extracted(self, tmp_path: Path) -> None:
        org = OrgStore(":memory:")
        ops = OpsStore(":memory:")
        pipeline = MissionPipeline(org, ops, outdir=tmp_path / "l")
        pipeline.run(title="حارس قسمة", objective=OBJECTIVE,
                     repo_path="examples/org_demo/fixture_repo", execution_policy=LOCAL_EXECUTION_POLICY)
        engine = LessonsEngine(org)
        assert engine.lessons_for_planning()
        # الدروس لا تمنح صلاحيات ولا تعدّل سياسات — واجهة قراءة فقط
        assert not hasattr(engine, "grant_permission")
        assert not hasattr(engine, "set_policy")
