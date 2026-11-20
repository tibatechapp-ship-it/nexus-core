"""Council Engine — محرك المجلس الكامل."""
from __future__ import annotations
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from src.council.trust import TrustBoundary  # noqa: E402
from src.council.gatekeeper import CouncilGatekeeper  # noqa: E402
from src.council.isolation import IsolationManager  # noqa: E402
from src.council.members import PROFILER, ANALYST, CRITIC  # noqa: E402

EventCallback = Callable[[str, Any], None]


@dataclass
class CouncilResult:
    verdict: str
    score: float
    consensus: bool
    rounds: int
    transcript: list
    elapsed: float
    security_events: list = field(default_factory=list)
    execution_ok: bool = True
    errors: list = field(default_factory=list)


class CouncilEngine:
    MAX_ROUNDS = 3

    def __init__(self, llm_router: Any = None, genome: Any = None) -> None:
        # ═══ Auto-create LLM router if not provided ═══
        if llm_router is None:
            try:
                from novamind.core.llm_router import LLMRouter
                llm_router = LLMRouter()
            except Exception:
                llm_router = None
        self.llm = llm_router
        self.trust = TrustBoundary()
        self.gatekeeper = CouncilGatekeeper()
        self.isolation = IsolationManager()
        self.members = [PROFILER, ANALYST, CRITIC]
        self.security_log: list[dict] = []
        # ═══ Genome v2 observer (v1.14.0) — None → the shared default ═══
        self._genome: Any = genome

    # خريطة توزيع المفاتيح على الأعضاء
    PROVIDER_MAP = {
        "profiler": "groq_01",
        "analyst": "groq_02",
        "critic": "groq_03",
    }

    def _call_llm(self, member: Any, prompt: str, context: str = "") -> str:
        """Call a real provider and fail closed on every invalid response."""
        verdict = self.gatekeeper.analyze(sender="context", content=context or prompt)
        if self.gatekeeper.is_blocked(verdict):
            self.security_log.append({
                "event": "context_blocked",
                "member": member.name,
                "verdict": verdict.level,
            })
            raise RuntimeError(f"محجوب: {verdict.reason}")

        if self.llm is None:
            raise RuntimeError("no real LLM provider configured")

        full_prompt = (
            f"{member.system_prompt}\n\n━━━ السياق ━━━\n{context}"
            f"\n\n━━━ المطلوب ━━━\n{prompt}"
        )
        try:
            result = self.llm.generate(
                prompt=full_prompt,
                system=member.system_prompt,
                temperature=0.3,
                max_tokens=member.max_output_length,
            )
        except Exception as exc:
            self.security_log.append({
                "event": "provider_call_failed",
                "member": member.name,
                "error_type": type(exc).__name__,
            })
            raise RuntimeError(
                f"LLM provider call failed: {type(exc).__name__}"
            ) from exc

        if not isinstance(result, dict):
            raise RuntimeError("LLM router returned an unstructured response")
        provider = str(result.get("provider") or "").strip().lower()
        if result.get("ok") is not True:
            raise RuntimeError("LLM provider returned an unsuccessful response")
        if result.get("simulated") or provider in {"mock", "mock-provider", "offline"}:
            raise RuntimeError("simulated provider response rejected")
        if not provider or provider == "unknown":
            raise RuntimeError("LLM response did not identify its provider")
        text = result.get("text")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("LLM provider returned an empty response")

        output_verdict = self.gatekeeper.analyze(sender=member.name, content=text)
        if self.gatekeeper.is_blocked(output_verdict):
            self.security_log.append({
                "event": "output_blocked",
                "member": member.name,
                "verdict": output_verdict.level,
            })
            raise RuntimeError(f"إجابة محجوبة: {output_verdict.reason}")
        return text

    def deliberate(
        self,
        question: str,
        context: str = "",
        on_event: EventCallback | None = None,
    ) -> CouncilResult:
        """مداولة كاملة — مع بث لحظي اختياري: on_event(event, payload)."""
        start = time.time()
        transcript: list[dict[str, Any]] = []

        def _emit(event: str, payload: Any) -> None:
            if on_event:
                try:
                    on_event(event, payload)
                except Exception:
                    pass

        def _failure_result(member: Any, phase: str, exc: Exception, rounds: int) -> CouncilResult:
            message = str(exc)[:180]
            transcript.append({
                "phase": phase,
                "member": member.name,
                "response": f"[فشل التنفيذ: {message}]",
            })
            self.security_log.append({
                "event": "council_execution_failed",
                "member": member.name,
                "phase": phase,
                "error_type": type(exc).__name__,
            })
            _emit("execution_failed", {
                "actor": member.name,
                "phase": phase,
                "error": type(exc).__name__,
            })
            return CouncilResult(
                verdict="human_review",
                score=0.0,
                consensus=False,
                rounds=rounds,
                transcript=transcript,
                elapsed=time.time() - start,
                security_events=list(self.security_log),
                execution_ok=False,
                errors=[f"{phase}: {type(exc).__name__}: {message}"],
            )

        self.isolation.prepare(self.members, question)
        _emit("phase", {"name": "independent", "label": "المرحلة 1: تحليل مستقل"})
        for member in self.members:
            time.sleep(0.3)
            ctx = self.isolation.get_context(member.name)
            try:
                response = self._call_llm(
                    member,
                    prompt=question + "\n\nاختم ردك بسطرين بالضبط:\n[الحكم: موافق] أو [الحكم: مرفوض] أو [الحكم: محايد]\n[التوصية: <خلاصة جوابك في ≤5 كلمات>]",
                    context=(context + "\n\n" + ctx) if context else ctx,
                )
            except Exception as exc:
                return _failure_result(member, "independent", exc, 0)
            self.isolation.commit(member.name, response)
            transcript.append({"phase": "independent", "member": member.name, "response": response})
            _emit("agent_action", {"actor": member.name, "phase": "independent", "text": response})

        # ═══ إجماع مبكر: اتجاه واضح بعد التحليل المستقل → تخطي النقاش (v1.9) ═══
        _ind = {e.get("member"): e.get("response", "")
                for e in transcript if e.get("phase") == "independent"}
        if len(_ind) >= 2 and self._consensus(_ind):  # type: ignore[arg-type]
            _emit("phase", {"name": "early_consensus",
                            "label": "إجماع مبكر — تم تخطي جولة النقاش"})
            verdict, score = self._judge(transcript)
            return CouncilResult(
                verdict=verdict, score=score, consensus=True,
                rounds=0, transcript=transcript,
                elapsed=time.time() - start, security_events=self.security_log,
            )

        current_round = 0
        last_consensus = False
        for round_num in range(self.MAX_ROUNDS):
            current_round = round_num + 1
            _emit("phase", {"name": "debate_" + str(current_round),
                            "label": "جولة النقاش " + str(current_round)})
            all_resp = self.isolation.reveal_for_debate()
            debate_ctx = "\n\n".join("[" + n + "]: " + r for n, r in all_resp.items())
            new_resp = {}
            for member in self.members:
                try:
                    resp = self._call_llm(
                        member,
                        prompt=("راجع الحجج التالية باختصار.\n\n"
                                "━━━ الحجج ━━━\n" + debate_ctx + "\n"
                                "━━━━━━━━━━━━\n\n"
                                "المطلوب: قرارك النهائي على السؤال المذكور في السياق أعلاه.\n"
                                "إن كان السؤال مقارنة (X أم Y)، فيجب أن يكون اسم الخيار في سطر التوصية.\n\n"
                                "اختم ردك بسطرين بالضبط لا غير:\n"
                                "  [الحكم: موافق] أو [الحكم: مرفوض] أو [الحكم: محايد]\n"
                                "  [التوصية: <اسم الخيار الموصى به من السؤال>]"),
                        context="السؤال الأصلي: " + question + "\n(تجاهل أي قرارات سابقة لنفس السؤال — ركّز على السؤال المطروح)",
                    )
                except Exception as exc:
                    return _failure_result(member, "debate_" + str(round_num + 1), exc, current_round)
                new_resp[member.name] = resp
                transcript.append({"phase": "debate_" + str(round_num+1),
                                   "member": member.name, "response": resp})
                _emit("agent_action", {"actor": member.name,
                                       "phase": "debate_" + str(round_num+1), "text": resp})
            if self._consensus(new_resp):
                last_consensus = True
                break

        _emit("phase", {"name": "judging", "label": "المرحلة النهائية: الحكم"})
        verdict, score = self._judge(transcript)
        return CouncilResult(
            verdict=verdict, score=score,
            consensus=last_consensus,
            rounds=current_round, transcript=transcript,
            elapsed=time.time() - start, security_events=self.security_log,
        )

    def _explicit_verdict(self, text: str | None) -> str | None:
        """يستخرج الحكم الصريح من نص الوكيل."""
        t = text or ""
        if "الحكم: موافق" in t:
            return "yes"
        if "الحكم: مرفوض" in t:
            return "no"
        if "الحكم: محايد" in t:
            return "mid"
        return None

    def _consensus(self, responses: dict[str, str]) -> bool:
        """Require explicit structured verdicts; keyword similarity is not consensus."""
        if len(responses) < 2:
            return False
        verdicts = [
            verdict
            for verdict in (self._explicit_verdict(response) for response in responses.values())
            if verdict is not None
        ]
        if len(verdicts) != len(responses):
            return False
        counts: dict[str, int] = {}
        for verdict in verdicts:
            counts[verdict] = counts.get(verdict, 0) + 1
        return max(counts.values(), default=0) >= 2

    def _genome_v2(self) -> Any:
        """العضو المراقب للجينوم v2 — يُستورد تأخيرياً، ولا يُسقط المجلس أبداً."""
        if getattr(self, "_genome", None) is None:
            try:
                from src.novamind.genome_v2 import get_genome_v2
                self._genome = get_genome_v2()
            except Exception:
                self._genome = False  # عُلِّم كغير متاح: لا نعيد المحاولة
        return self._genome or None

    def _observe_genome(self, transcript: list[dict[str, Any]], verdict: str) -> None:
        """يطوي حكم كل عضو في الجينوم v2 — أفضل جهد، لا يمسّ الحكم النهائي."""
        observer = self._genome_v2()
        if observer is None:
            return
        try:
            known = {m.name for m in self.members}
            stances: dict[str, str] = {}
            for entry in transcript:
                member = entry.get("member")
                stance = self._explicit_verdict(entry.get("response", ""))
                if member in known and stance:
                    stances[member] = stance
            if stances:
                observer.observe_council(stances, verdict)
        except Exception:
            pass

    def _judge(self, transcript: list[dict[str, Any]]) -> tuple[str, float]:
        """الحكم النهائي + طيّ أحكام الأعضاء في الجينوم v2 (مراقبة فقط)."""
        verdict, score = self._judge_verdict(transcript)
        self._observe_genome(transcript, verdict)
        return verdict, score

    def _judge_verdict(self, transcript: list[dict[str, Any]]) -> tuple[str, float]:
        """Decide only from explicit member verdicts; otherwise require human review."""
        explicit: dict[str, str] = {}
        known_members = {"profiler", "analyst", "critic"}
        for entry in transcript:
            member = entry.get("member")
            if member not in known_members:
                continue
            verdict = self._explicit_verdict(entry.get("response", ""))
            if verdict is not None:
                explicit[member] = verdict

        if len(explicit) < 2:
            return "human_review", 0.5

        counts: dict[str, int] = {}
        for verdict in explicit.values():
            counts[verdict] = counts.get(verdict, 0) + 1

        top = max(counts, key=lambda value: counts[value])
        if counts[top] < 2:
            return "human_review", 0.5
        if top == "yes":
            return "approve", 0.85
        if top == "no":
            return "reject", 0.15
        return "human_review", 0.5
