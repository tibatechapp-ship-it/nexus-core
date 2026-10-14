"""Council Engine — محرك المجلس الكامل."""
from __future__ import annotations
import os, sys, time
from dataclasses import dataclass, field

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from src.council.trust import TrustBoundary
from src.council.gatekeeper import CouncilGatekeeper
from src.council.isolation import IsolationManager
from src.council.members import PROFILER, ANALYST, CRITIC, JUDGE_CONFIG


@dataclass
class CouncilResult:
    verdict: str
    score: float
    consensus: bool
    rounds: int
    transcript: list
    elapsed: float
    security_events: list = field(default_factory=list)


class CouncilEngine:
    MAX_ROUNDS = 3

    def __init__(self, llm_router=None):
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
        self.security_log = []

    def _call_llm(self, member, prompt, context=""):
        # فحص السياق
        v = self.gatekeeper.analyze(sender="context", content=context or prompt)
        if self.gatekeeper.is_blocked(v):
            self.security_log.append({"event": "context_blocked", "member": member.name, "verdict": v.level})
            return f"[محجوب: {v.reason}]"
        # استدعاء LLM
        full = f"{member.system_prompt}\n\n━━━ السياق ━━━\n{context}\n\n━━━ المطلوب ━━━\n{prompt}"
        if self.llm:
            try:
                result = self.llm.generate(prompt=full, system=member.system_prompt,
                                            temperature=0.3, max_tokens=member.max_output_length)
                text = result.get("text", "") if isinstance(result, dict) else str(result)
            except Exception as e:
                text = f"[خطأ LLM: {e}]"
        else:
            text = f"[{member.name}]: تحليل افتراضي للطلب"
        # فحص الإجابة
        out_v = self.gatekeeper.analyze(sender=member.name, content=text)
        if self.gatekeeper.is_blocked(out_v):
            self.security_log.append({"event": "output_blocked", "member": member.name, "verdict": out_v.level})
            return f"[إجابة محجوبة: {out_v.reason}]"
        return text

    def deliberate(self, question, context=""):
        start = time.time()
        transcript = []
        # المرحلة 1: تحليل مستقل
        self.isolation.prepare(self.members, question)
        for member in self.members:
            ctx = self.isolation.get_context(member.name)
            response = self._call_llm(member, prompt=question,
                                       context=f"{context}\n\n{ctx}" if context else ctx)
            self.isolation.commit(member.name, response)
            transcript.append({"phase": "independent", "member": member.name, "response": response})
        # المرحلة 2: نقاش
        current_round = 0
        for round_num in range(self.MAX_ROUNDS):
            current_round = round_num + 1
            all_resp = self.isolation.reveal_for_debate()
            debate_ctx = "\n\n".join(f"[{n}]: {r}" for n, r in all_resp.items())
            new_resp = {}
            for member in self.members:
                resp = self._call_llm(member,
                    prompt=f"راجع حجج الآخرين وردّ عليها:\n\n{debate_ctx}\n\nقدّم: نقاط الاتفاق، الاختلاف، الردّ.",
                    context=f"السؤال: {question}")
                new_resp[member.name] = resp
                transcript.append({"phase": f"debate_{round_num+1}", "member": member.name, "response": resp})
            if self._consensus(new_resp):
                break
        # المرحلة 3: الحكم (كود)
        verdict, score = self._judge(transcript)
        return CouncilResult(
            verdict=verdict, score=score, consensus=(score >= JUDGE_CONFIG["thresholds"]["approve"]),
            rounds=current_round, transcript=transcript,
            elapsed=time.time() - start, security_events=self.security_log,
        )

    def _consensus(self, responses):
        if len(responses) < 2:
            return True
        all_words = [set(r.lower().split()) for r in responses.values()]
        common = all_words[0].intersection(*all_words[1:])
        return len(common) > 30

    def _judge(self, transcript):
        scores = {"profiler": 0.5, "analyst": 0.5, "critic": 0.5}
        for entry in transcript:
            m = entry["member"]
            if m not in scores:
                continue
            r = entry["response"].lower()
            pos = sum(1 for w in ["آمن", "موافق", "مقبول", "safe", "approve"] if w in r)
            neg = sum(1 for w in ["خطر", "مرفوض", "غير آمن", "danger", "reject"] if w in r)
            scores[m] += (pos - neg) * 0.1
        w = JUDGE_CONFIG["weights"]
        final = sum(scores[k] * w[k] for k in scores)
        final = max(0.0, min(1.0, final))
        t = JUDGE_CONFIG["thresholds"]
        if final >= t["approve"]:
            verdict = "approve"
        elif final <= t["reject"]:
            verdict = "reject"
        else:
            verdict = "human_review"
        return verdict, final
