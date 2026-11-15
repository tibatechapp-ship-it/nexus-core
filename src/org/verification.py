"""قسم التحقق المستقل — لا ادعاء بلا دليل، ولا إصلاح بلا إعادة إنتاج.

القواعد المعلنة:

* **الادعاء يُحسم بالأدلة فقط**: كل ادعاء يحتاج دليلًا واحدًا على الأقل
  من النوع المقبول لطبيعته — «إصلاح» يحتاج دليل اختبار ناجح على الرقعة،
  «نجاح اختبار» يحتاج تفاصيل تشغيل حقيقية (رمز خروج، أمر، زمن).
* **رفض غير المدعوم صريح**: ادعاء بلا أدلة أو بأدلة فاشلة يُحسم
  ``rejected`` بمبرر مكتوب — لا يبقى معلّقًا ولا يُصدَّق بالتسامح.
* **إعادة الإنتاج مستقلة**: قسم التحقق يعيد تشغيل اختبارات الرقعة بنفسه
  داخل العزل — لا يكفي أن يقول القسم المنتج «نجح».
* **تقرير تحقق حتمي**: نفس الحالة تعطي نفس التقرير حرفيًا — قابل للاختبار.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from src.org.agents import AgentRuntime, AgentSpec
from src.org.contracts import Claim, Evidence, Mission
from src.org.sandbox import WorkspaceRunner, Worktree
from src.org.store import OrgStore

__all__ = ["VerificationReport", "VerificationEngine"]

#: نوع الدليل المقبول لكل نوع ادعاء — عقد الحسم المعلن.
REQUIRED_EVIDENCE: dict[str, tuple[str, ...]] = {
    "fix": ("test_result", "replay"),
    "test_pass": ("test_result",),
    "no_regression": ("test_result", "replay"),
    "observation": ("scan", "log", "diff", "static_analysis", "test_result",
                    "replay"),
}

#: أصناف ادعاءات معلنة — ادعاء بصنف خارجها يرفع في البناء.
CLAIM_KINDS = frozenset(REQUIRED_EVIDENCE)


@dataclass(frozen=True)
class VerificationReport:
    """تقرير تحقق مهمة — حتمي: نفس الحالة تعطي نفس النص."""

    mission_id: str
    verified: int = 0
    rejected: int = 0
    inconclusive: int = 0
    unresolved: int = 0          # ادعاءات لم تُحسم أصلاً
    reproduced_fix: bool = False
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id, "verified": self.verified,
            "rejected": self.rejected, "inconclusive": self.inconclusive,
            "unresolved": self.unresolved,
            "reproduced_fix": self.reproduced_fix, "reasons": self.reasons,
        }

    def summary_line(self) -> str:
        """سطر واحد حتمي للتقرير الهندسي واللوحة."""
        return (f"محقَّق {self.verified} · مرفوض {self.rejected} · "
                f"غير محسوم {self.inconclusive} · معلّق {self.unresolved} · "
                f"إعادة إنتاج الإصلاح: {'نعم' if self.reproduced_fix else 'لا'}")


class VerificationEngine:
    """محرك التحقق — يحسم كل ادعاء بالأدلة ويعيد إنتاج الإصلاح بنفسه."""

    def __init__(self, runtime: AgentRuntime, store: OrgStore,
                 runner: WorkspaceRunner) -> None:
        self.runtime = runtime
        self.store = store
        self.runner = runner

    # ── حسم الادعاءات ─────────────────────────────────────────────────────

    def resolve_claim(self, claim: Claim,
                      evidence: list[Evidence]) -> Claim:
        """حسم ادعاء واحد — أدلة كافية = محقَّق، فاشلة = مرفوض، نقص = غير محسوم."""
        if claim.claim_kind not in CLAIM_KINDS:
            raise ValueError(f"صنف ادعاء غير معلن: {claim.claim_kind}")
        required = REQUIRED_EVIDENCE[claim.claim_kind]
        # المطابقة صارمة: دليل مرتبط بهذا الادعاء فقط — دليل سياق
        # المهمة (claim_id فارغ) لا يثبت ادعاءً أبدًا، وإلا نجح أخضر
        # الأساس في إثبات ادعاء رقعة حمراء.
        mine = [e for e in evidence
                if e.claim_id == claim.id and e.kind in required]
        if not mine:
            return self.store.claim_resolve(
                claim.id, "rejected",
                "لا أدلة من الأنواع المطلوبة "
                f"{required} — الادعاء غير مدعوم",
                [])
        passing = [e for e in mine if e.ok]
        if not passing:
            return self.store.claim_resolve(
                claim.id, "rejected",
                "كل الأدلة المتاحة فاشلة — الادعاء مرفوض",
                [e.id for e in mine])
        return self.store.claim_resolve(
            claim.id, "verified", f"أدلة كافية ({len(passing)}) من {required}",
            [e.id for e in passing])

    # ── إعادة إنتاج الإصلاح ───────────────────────────────────────────────

    def reproduce_fix(self, mission: Mission, worktree: Worktree | None,
                      test_target: str = "",
                      fix_claim_ids: list[str] | None = None
                      ) -> tuple[bool, list[Evidence]]:
        """إعادة تشغيل اختبارات الرقعة بنفسه — لا ثقة بقول القسم المنتج.

        الدليل الناتج يُربط بكل ادعاء إصلاح معلن — دليل بلا ربط لا يثبت
        شيئًا في الحسم الصارم.
        """
        targets = fix_claim_ids or [""]
        if worktree is None:
            evs = [self.store.add_evidence(Evidence(
                mission_id=mission.id, kind="replay",
                detail={"reproduced": False,
                        "reason": "لا نسخة عمل لإعادة الإنتاج"},
                captured_by="verification:auditor", ok=False, claim_id=cid))
                for cid in targets]
            return False, evs
        t0 = time.time()
        result = self.runner.run_python_tests(worktree.root, target=test_target)
        ok = result.returncode == 0 and not result.timed_out
        evs = [
            self.store.add_evidence(Evidence(
                mission_id=mission.id, kind="replay",
                detail={**result.to_detail(), "reproduced": ok,
                        "verify_ms": round((time.time() - t0) * 1000, 2)},
                captured_by="verification:auditor", ok=ok, claim_id=cid))
            for cid in targets
        ]
        return ok, evs

    # ── تقرير المهمة ──────────────────────────────────────────────────────

    def verify_mission(self, mission: Mission, claims: list[Claim],
                       evidence: list[Evidence], worktree: Worktree | None,
                       test_target: str = "") -> VerificationReport:
        """تحقق كامل للمهمة — حسم كل ادعاء + إعادة إنتاج + تقرير حتمي.

        الترتيب معلن: إعادة إنتاج الإصلاح أولًا (تضيف دليل ``replay``
        للمتجر)، ثم حسم كل ادعاء على الأدلة المجتمعة من الوسيط والمتجر.
        """
        reasons: list[str] = []
        verified = rejected = inconclusive = 0
        has_fix = any(c.claim_kind == "fix" for c in claims)
        reproduced = False
        if has_fix:
            # ادعاءات الإصلاح المخزنة بمعرّفاتها — الدليل يُربط بها حتميًا
            stored_all = {c.statement: c
                          for c in self.store.claims_for(mission.id)}
            fix_ids = [
                stored_all[c.statement].id if c.statement in stored_all
                else self.store.add_claim(c).id
                for c in claims if c.claim_kind == "fix"
            ]
            reproduced, _ = self.reproduce_fix(
                mission, worktree, test_target, fix_claim_ids=fix_ids)
            if not reproduced:
                reasons.append("إعادة إنتاج الإصلاح فشلت داخل العزل")
        else:
            reasons.append("لا ادعاء إصلاح — لا إعادة إنتاج مطلوبة")
        combined = list(evidence) + self.store.evidence_for(mission.id)
        # الحسم على النسخ المخزنة — نسخة الحقيبة بلا معرّف لا تُحسم
        stored_by_statement = {c.statement: c
                               for c in self.store.claims_for(mission.id)}
        for claim in claims:
            stored = stored_by_statement.get(claim.statement)
            if stored is None:
                stored = self.store.add_claim(claim)
                stored_by_statement[claim.statement] = stored
            resolved = self.resolve_claim(stored, combined)
            if resolved.status == "verified":
                verified += 1
            elif resolved.status == "rejected":
                rejected += 1
                reasons.append(f"مرفوض: {claim.statement[:120]}")
            else:
                inconclusive += 1
        # رأي نموذج مستقل يُسجَّل دليلًا نصيًا — لا يغيّر الحكم الكودي
        spec = AgentSpec(role="verification:auditor", dept="verification",
                         mission_id=mission.id, max_retries=1)
        prompt = (f"ادعاءات: {[c.statement[:80] for c in claims]}\n"
                  "قيّم كفاية الأدلة المرفقة بالمهمة. أجب JSON بمفتاح assessment.")
        outcome = self.runtime.ask_json(spec, prompt)
        if outcome.success:
            assessment = str(outcome.data.get("assessment", ""))
            self.store.add_evidence(Evidence(
                mission_id=mission.id, kind="log",
                detail={"assessment": assessment},
                captured_by="verification:auditor", ok=True))
        stored_claims = self.store.claims_for(mission.id)
        unresolved = sum(1 for c in stored_claims if c.status == "unverified")
        report = VerificationReport(
            mission_id=mission.id, verified=verified, rejected=rejected,
            inconclusive=inconclusive, unresolved=unresolved,
            reproduced_fix=(has_fix and reproduced), reasons=reasons)
        self.store.audit("verification.completed", mission.id,
                         report.to_dict())
        return report
