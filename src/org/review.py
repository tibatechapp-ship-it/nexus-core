"""مجلس المراجعة المستقلة — عدسات متعددة وإجماع وحسم خلاف.

القواعد المعلنة:

* **استقلال حقيقي**: كل عدسة مراجع مستقل بعقد ونموذج ومطالبة مستقلة —
  ومراجع لا يراجع تعديلَ دوره هو (فحص صريح في ``collect``).
* **إجماع معلن**: توافق = لا مراجع يطلب تغييرات بقضية حرجة/عالية
  والمتوسط ≥ العتبة المعلنة — خلاف ذلك «طلب تغييرات» بأسباب مرقمة.
* **حسم الخلاف بجولة نقاش واحدة**: مراجعات متضاربة تُعاد بمعرفة كل
  مراجع برأي الآخرين — جولة ثانية بحد أقصى معلن، ثم قرار المجلس حتمي
  بترتيب الأسباب لا بالتصويت الصامت.
* **كل مراجعة تُخزَّن**: لا مراجعة شفوية — السجل في المتجر بمعرّفه.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from src.org.agents import AgentOutcome, AgentRuntime, AgentSpec
from src.org.contracts import REVIEW_LENSES, Review
from src.org.store import OrgStore

__all__ = ["CouncilDecision", "ReviewCouncil"]

#: عتبة الإجماع المعلنة — المتوسط لا ينزل عنها مع غياب القضايا العالية.
CONSENSUS_THRESHOLD = 80

#: درجات الخطورة التي تمنع التوافق مهما كان المتوسط.
BLOCKING_SEVERITIES = frozenset({"critical", "high"})


@dataclass(frozen=True)
class CouncilDecision:
    """قرار المجلس — الحكم والأسباب والمراجعات الحاكمة."""

    verdict: str                    # approve | request_changes
    mean_score: int
    reasons: list[str] = field(default_factory=list)
    rounds: int = 1
    review_ids: list[str] = field(default_factory=list)
    dissent: list[str] = field(default_factory=list)


class ReviewCouncil:
    """مجلس المراجعة — جمع مستقل، فحص خلاف، جولة نقاش، قرار محفوظ."""

    def __init__(self, runtime: AgentRuntime, store: OrgStore,
                 threshold: int = CONSENSUS_THRESHOLD) -> None:
        self.runtime = runtime
        self.store = store
        self.threshold = threshold

    # ── الجمع المستقل ─────────────────────────────────────────────────────

    def collect(self, mission_id: str, task_id: str, dev_role: str,
                diff_text: str, notes: str,
                lenses: list[str] | None = None) -> list[Review]:
        """مراجعات مستقلة بعدسات معلنة — مطالبة كل مراجع تحمل الرقعة."""
        chosen = lenses or list(REVIEW_LENSES)
        reviews: list[Review] = []
        for lens in chosen:
            spec = AgentSpec(
                role=f"review:{lens}", dept="code_review", mission_id=mission_id,
                task_id=task_id, max_retries=1,
            )
            if spec.role == dev_role:
                # استقلال معلن: لا مراجع يوافق على تعديله هو
                continue
            prompt = (
                f"راجع الرقعة التالية بعدسة «{lens}» فقط.\n"
                f"NOTES:\n{notes}\n"
                f"DIFF:\n{diff_text}\n\n"
                "أجب JSON بمفاتيح: verdict (approve|request_changes), "
                "score (0..100), issues (قائمة {severity,file,line,message}), "
                "reasoning."
            )
            outcome = self.runtime.ask_json(spec, prompt)
            review = self._outcome_to_review(mission_id, task_id, lens, outcome,
                                             debate_round=0)
            reviews.append(review)
        return reviews

    def _outcome_to_review(self, mission_id: str, task_id: str, lens: str,
                           outcome: AgentOutcome, debate_round: int) -> Review:
        """تحويل ناتج وكيل إلى سجل مراجعة — فشل الوكيل = طلب تغييرات صريح."""
        if not outcome.success:
            return Review(
                mission_id=mission_id, task_id=task_id,
                reviewer=f"review:{lens}", lens=lens,
                verdict="request_changes", score=0,
                comments=f"فشل المراجع: {outcome.error}",
                issues=[{"severity": "high", "file": "", "line": 0,
                         "message": "مراجع غير قادر على الحكم — لا توافق صامت"}],
                debate_round=debate_round,
            )
        data = outcome.data
        verdict = "approve" if data.get("verdict") == "approve" \
            else "request_changes"
        score = int(data.get("score", 0))
        issues = [i for i in data.get("issues", []) if isinstance(i, dict)]
        return Review(
            mission_id=mission_id, task_id=task_id,
            reviewer=f"review:{lens}", lens=lens, verdict=verdict,
            score=score, comments=str(data.get("reasoning", "")),
            issues=issues, debate_round=debate_round,
        )

    # ── الإجماع والحسم ────────────────────────────────────────────────────

    def decide(self, mission_id: str, task_id: str,
               reviews: list[Review]) -> CouncilDecision:
        """قرار المجلس حتمي — مراجعات محفوظة وأسباب مرقمة وخلاف مسمّى."""
        for review in reviews:
            self.store.add_review(review)
        if not reviews:
            return CouncilDecision(
                verdict="request_changes", mean_score=0,
                reasons=["لا مراجعات — لا توافق بلا مراجعين مستقلين"],
                rounds=0)
        blocking: list[str] = []
        for review in reviews:
            for issue in review.issues:
                if str(issue.get("severity", "")).lower() in BLOCKING_SEVERITIES:
                    blocking.append(
                        f"[{review.lens}] {issue.get('message', '')} "
                        f"({issue.get('file', '')}:{issue.get('line', 0)})")
        mean = sum(r.score for r in reviews) // len(reviews)
        requests = [r for r in reviews if r.verdict == "request_changes"]
        if blocking or mean < self.threshold:
            reasons = []
            if blocking:
                reasons.extend(sorted(blocking))
            if mean < self.threshold:
                reasons.append(
                    f"متوسط الدرجات {mean} دون عتبة الإجماع {self.threshold}")
            for r in sorted(requests, key=lambda x: x.lens):
                if r.comments:
                    reasons.append(f"[{r.lens}] {r.comments[:200]}")
            return CouncilDecision(
                verdict="request_changes", mean_score=mean,
                reasons=reasons, rounds=1,
                review_ids=[r.id for r in reviews],
                dissent=sorted(r.lens for r in requests))
        return CouncilDecision(
            verdict="approve", mean_score=mean, reasons=["توافق العدسات"],
            rounds=1, review_ids=[r.id for r in reviews])

    def review_with_debate(self, mission_id: str, task_id: str,
                           dev_role: str, diff_text: str, notes: str = "",
                           max_rounds: int = 2) -> tuple[CouncilDecision,
                                                         list[Review]]:
        """مراجعة كاملة مع جولة نقاش واحدة عند الخلاف — حد معلن.

        الجولة الثانية تعيد المراجعات المتضاربة فقط بمعرفة كل مراجع برأي
        الآخرين؛ قرار الجولة الثانية نهائي حتميًا بترتيب الأسباب.
        """
        reviews = self.collect(mission_id, task_id, dev_role, diff_text, notes)
        decision = self.decide(mission_id, task_id, reviews)
        rounds = 1
        if decision.verdict == "request_changes" and decision.dissent \
                and max_rounds >= 2:
            rounds = 2
            dissent_reviews = [
                r for r in reviews if r.lens in decision.dissent]
            opinions = [
                {"lens": r.lens, "verdict": r.verdict, "score": r.score,
                 "comments": r.comments}
                for r in dissent_reviews
            ]
            debate_prompt = (
                "جولة نقاش: هذه آراء المراجعين المتضاربة عن الرقعة:\n"
                f"{json.dumps(opinions, ensure_ascii=False)}\n"
                f"DIFF:\n{diff_text}\n\n"
                "أعد التقييم بمعرفة الآراء. أجب JSON كما قبل."
            )
            new_reviews: list[Review] = []
            for lens in decision.dissent:
                spec = AgentSpec(
                    role=f"review:{lens}", dept="code_review",
                    mission_id=mission_id, task_id=task_id, max_retries=1)
                outcome = self.runtime.ask_json(spec, debate_prompt)
                new_reviews.append(self._outcome_to_review(
                    mission_id, task_id, lens, outcome, debate_round=2))
            # المراجعات غير المتضاربة تبقى حاكمة مع جولة النقاش
            kept = [r for r in reviews if r.lens not in decision.dissent]
            decision = self.decide(mission_id, task_id, kept + new_reviews)
            rounds = max(rounds, decision.rounds or 2)
        return decision, reviews
