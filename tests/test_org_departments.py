"""اختبارات الأقسام الثمانية — عامل كل قسم بمدخله وناتجه المعلنين.

القواعد المفروضة: التطوير على نسخة عمل لا الأصل، الأدلة مرتبطة
بادعاءاتها، الإصدار يفتح تذكرة بـpublish_allowed=False وطلب موافقة،
وفشل قسم رفع صريح لا صمت.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.org.agents import AgentRuntime, ToolRegistry
from src.org.departments import (
    DepartmentError,
    Departments,
    DevelopmentDept,
    MissionContext,
    RepoIntelDept,
    RequirementsOffice,
    SecurityDept,
)
from src.org.providers import ProviderConfig, ProviderPool
from src.org.sandbox import WorkspaceRunner
from src.org.store import OrgStore
from src.ops.store import OpsStore

OBJECTIVE = ("أضف حارس قسمة على صفر إلى دالة divide في وحدة calc.mathops "
             "مع اختبارات للحدية")

class DeterministicCoderConnector:
    """Test-only coder connector: deterministic detector and safe RepairPlan."""

    def __init__(self) -> None:
        self.usage_total = {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
        self.providers_used: set[str] = set()
        self.models_used: set[str] = set()

    async def generate(self, prompt: str) -> dict:
        import json
        if "defect-discovery stage" in prompt:
            return {"ok": True, "reply": "[]"}
        if "planning stage" in prompt:
            plan = {
                "goal": "Add explicit division-by-zero guard",
                "defects": [],
                "steps": [{
                    "file": "calc/mathops.py",
                    "action": "edit",
                    "reason": "Reject zero divisor",
                    "find": "def divide(a, b):\\n    return a / b",
                    "patch_hint": (
                        "def divide(a, divisor):\\n"
                        "    if divisor == 0:\\n"
                        "        raise ZeroDivisionError('division by zero')\\n"
                        "    return a / divisor"
                    ),
                    "risk": "low",
                }],
                "tests_to_run": ["tests/test_mathops.py"],
            }
            return {"ok": True, "reply": json.dumps(plan)}
        return {"ok": False, "error": "unexpected coder prompt"}




@pytest.fixture()
def fixture_repo(tmp_path: Path) -> Path:
    pkg = tmp_path / "calc"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mathops.py").write_text(
        "def divide(a, b):\n    return a / b\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_mathops.py").write_text(
        "from calc.mathops import divide\n"
        "def test_divide_normal():\n    assert divide(10, 2) == 5\n",
        encoding="utf-8")
    return tmp_path


@pytest.fixture()
def depts(tmp_path: Path) -> Departments:
    org = OrgStore(":memory:")
    ops = OpsStore(":memory:")
    return Departments(
        ProviderPool([ProviderConfig()]), org, ops,
        outdir=tmp_path / "reports",
        coder_connector_factory=lambda runtime, mission_id: DeterministicCoderConnector(),
    )


@pytest.fixture()
def mission(depts: Departments) -> object:
    from src.org.contracts import Mission
    return depts.org_store.create_mission(Mission(
        title="حارس قسمة", objective=OBJECTIVE))


class TestRequirements:
    def test_criteria_extracted(self, depts: Departments,
                                mission: object) -> None:
        ctx = MissionContext(mission=mission)  # type: ignore[arg-type]
        out = depts.requirements.run(ctx)
        assert out["status"] == "ok"
        assert out["acceptance_criteria"]
        claim = out["claim"]
        assert claim.claim_kind == "observation"
        ev = depts.runtime.store.evidence_for(
            ctx.mission.id, claim_id=claim.id)  # type: ignore[union-attr]
        assert ev and ev[0].kind == "log"


class TestIntel:
    def test_map_and_worktree(self, depts: Departments, mission: object,
                              fixture_repo: Path) -> None:
        from src.org.contracts import Mission
        stored = depts.org_store.mission_get(mission.id)  # type: ignore[attr-defined]
        stored = depts.org_store.mission_update(Mission(  # type: ignore[arg-type]
            title=stored.title, objective=stored.objective,
            repo_path=str(fixture_repo), id=stored.id,
            phase=stored.phase, status=stored.status))
        ctx = MissionContext(mission=stored)
        out = depts.intel.run(ctx)
        assert out["status"] == "ok"
        assert "calc/mathops.py" in out["affected"]["direct"]
        assert ctx.worktree is not None
        assert "tests/test_mathops.py" in out["worktree_files"]

    def test_missing_repo_rejected(self, depts: Departments,
                                   mission: object) -> None:
        ctx = MissionContext(mission=mission)  # type: ignore[arg-type]
        with pytest.raises(DepartmentError, match="مستودع"):
            depts.intel.run(ctx)


class TestDevelopment:
    def test_patch_applied_to_worktree_not_original(
            self, depts: Departments, mission: object,
            fixture_repo: Path) -> None:
        from src.org.contracts import Mission
        intel = RepoIntelDept(depts.runtime, depts.guard)
        stored = depts.org_store.mission_get(mission.id)  # type: ignore[attr-defined]
        stored = depts.org_store.mission_update(Mission(  # type: ignore[arg-type]
            title=stored.title, objective=stored.objective,
            repo_path=str(fixture_repo), id=stored.id,
            phase=stored.phase, status=stored.status))
        ctx = MissionContext(mission=stored)
        intel.run(ctx)
        out = depts.development.run(ctx)
        assert out["status"] == "ok" and out["applied"]
        assert ctx.diff_text.startswith("--- a/") or \
            ctx.diff_text.startswith("***") or "--- a/" in ctx.diff_text
        # الأصل لم يتغير
        original = (fixture_repo / "calc" / "mathops.py").read_text(
            encoding="utf-8")
        assert "if divisor == 0" not in original
        # نسخة العمل تغيّرت
        assert ctx.worktree is not None
        patched = ctx.worktree.read("calc/mathops.py")
        assert "if divisor == 0" in patched

    def test_unknown_dev_kind_rejected(self, depts: Departments,
                                       mission: object) -> None:
        with pytest.raises(DepartmentError, match="غير معلن"):
            depts.development.run(MissionContext(mission=mission),  # type: ignore[arg-type]
                                  dev_kind="magic")


class TestSecurity:
    def test_clean_repo_no_blockers(self, depts: Departments,
                                    mission: object,
                                    fixture_repo: Path) -> None:
        from src.org.contracts import Mission
        stored = depts.org_store.mission_get(mission.id)  # type: ignore[attr-defined]
        stored = depts.org_store.mission_update(Mission(  # type: ignore[arg-type]
            title=stored.title, objective=stored.objective,
            repo_path=str(fixture_repo), id=stored.id,
            phase=stored.phase, status=stored.status))
        ctx = MissionContext(mission=stored)
        out = depts.security.run(ctx, requirements_text="pytest\n")
        assert out["blocking_count"] == 0
        assert out["report"]["counts"]["secrets"] == 0

    def test_secret_in_patch_blocked(self, depts: Departments,
                                     mission: object) -> None:
        from src.org.sandbox import Worktree
        ctx = MissionContext(mission=mission)  # type: ignore[arg-type]
        ctx.worktree = Worktree.from_source(Path("."), files=[])
        ctx.worktree.write("leak.py", 'token = "ghp_' + "a" * 40 + '"\n')
        ctx.changed_files = ["leak.py"]
        out = depts.security.run(ctx)
        assert out["blocking_count"] >= 1
        findings = out["findings"]
        assert any(f.severity == "critical" for f in findings)


class TestRelease:
    def test_ticket_and_approval_with_human_gate(
            self, depts: Departments, mission: object) -> None:
        from src.org.contracts import Mission
        ctx = MissionContext(mission=mission)  # type: ignore[arg-type]
        ctx.diff_text = "--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n-x\n+y\n"
        out = depts.release.run(ctx)
        assert out["publish_allowed"] is False
        ticket = depts.ops_store.ticket_get(out["ticket_id"])
        assert ticket is not None and ticket.publish_allowed is False
        approvals = depts.org_store.approvals_for(mission.id)  # type: ignore[attr-defined]
        assert approvals and approvals[0].subject == out["ticket_id"]
        assert Path(out["report_path"]).exists()
        assert Path(out["patch_path"]).exists()

    def test_report_contains_required_sections(
            self, depts: Departments, mission: object) -> None:
        from src.org.contracts import Mission
        ctx = MissionContext(mission=mission)  # type: ignore[arg-type]
        ctx.diff_text = "--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n-x\n+y\n"
        out = depts.release.run(ctx)
        report = Path(out["report_path"]).read_text(encoding="utf-8")
        for section in ("معايير القبول", "ما تغيّر", "المراجعة المستقلة",
                        "الأمن", "الاختبارات", "الدمج"):
            assert section in report


class TestTooling:
    def test_verify_tooling(self, depts: Departments) -> None:
        checks = depts.verify_tooling()
        assert checks["tools"] is True
        assert checks["sandbox"] is True

    def test_departments_wired(self, depts: Departments) -> None:
        assert depts.requirements is not None
        assert depts.intel is not None
        assert depts.development is not None
        assert depts.security is not None
        assert depts.qa is not None
        assert depts.council is not None
        assert depts.release is not None
