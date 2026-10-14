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

    # خريطة توزيع المفاتيح على الأعضاء
    PROVIDER_MAP = {
        "profiler": "groq_01",
        "analyst": "groq_02",
        "critic": "groq_03",
    }

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
                # ═══ نترك Router يختار تلقائياً ═══
                result = self.llm.generate(
                    prompt=full,
                    system=member.system_prompt,
                    temperature=0.3,
                    max_tokens=member.max_output_length,
                )
                # ═══ إظهار الأخطاء بدلاً من إخفائها ═══
                if isinstance(result, dict):
                    if result.get("ok"):
                        text = result.get("text", "")
                    else:
                        err = str(result.get("error", "unknown"))[:150]
                        text = f"[فشل LLM: {err}]"
                else:
                    text = str(result)
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

    def deliberate(self, question, context="", on_event=None):
        """مداولة كاملة — مع بث لحظي اختياري: on_event(event, payload)."""
        start = time.time()
        transcript = []

        def _emit(event, payload):
            if on_event:
                try:
                    on_event(event, payload)
                except Exception:
                    pass

        self.isolation.prepare(self.members, question)
        _emit("phase", {"name": "independent", "label": "المرحلة 1: تحليل مستقل"})
        for member in self.members:
            import time as _t; _t.sleep(0.3)
            ctx = self.isolation.get_context(member.name)
            response = self._call_llm(member, prompt=question,
                                      context=(context + "\n\n" + ctx) if context else ctx)
            self.isolation.commit(member.name, response)
            transcript.append({"phase": "independent", "member": member.name, "response": response})
            _emit("agent_action", {"actor": member.name, "phase": "independent", "text": response})

        current_round = 0
        for round_num in range(self.MAX_ROUNDS):
            current_round = round_num + 1
            _emit("phase", {"name": "debate_" + str(current_round),
                            "label": "جولة النقاش " + str(current_round)})
            all_resp = self.isolation.reveal_for_debate()
            debate_ctx = "\n\n".join("[" + n + "]: " + r for n, r in all_resp.items())
            new_resp = {}
            for member in self.members:
                resp = self._call_llm(member,
                    prompt="راجع حجج الآخرين:\n\n" + debate_ctx +
                    "\n\nالمطلوب: رأي جديد — لا تكرر السابق.\n"
                    "اختم بسطر أخير: [الحكم: موافق] أو [الحكم: مرفوض] أو [الحكم: محايد]",
                    context="السؤال: " + question)
                new_resp[member.name] = resp
                transcript.append({"phase": "debate_" + str(round_num+1),
                                   "member": member.name, "response": resp})
                _emit("agent_action", {"actor": member.name,
                                       "phase": "debate_" + str(round_num+1), "text": resp})
            if self._consensus(new_resp):
                break

        _emit("phase", {"name": "judging", "label": "المرحلة النهائية: الحكم"})
        verdict, score = self._judge(transcript)
        return CouncilResult(
            verdict=verdict, score=score,
            consensus=(score >= JUDGE_CONFIG["thresholds"]["approve"]),
            rounds=current_round, transcript=transcript,
            elapsed=time.time() - start, security_events=self.security_log,
        )

    def _explicit_verdict(self, text):
        """يستخرج الحكم الصريح من نص الوكيل."""
        t = text or ""
        if "الحكم: موافق" in t: return "yes"
        if "الحكم: مرفوض" in t: return "no"
        if "الحكم: محايد" in t: return "mid"
        return None

    def _consensus(self, responses):
        """أغلبية الأحكام الصريحة (2/3) — والطريقة الكلمية احتياط."""
        if len(responses) < 2:
            return True
        verdicts = [self._explicit_verdict(r) for r in responses.values()]
        if all(v is not None for v in verdicts):
            counts = {}
            for v in verdicts:
                counts[v] = counts.get(v, 0) + 1
            return max(counts.values()) >= len(verdicts) // 2 + 1
        # fallback كلمي
        positive = ["مقبول", "آمن", "موافق", "approve", "safe"]
        negative = ["مرفوض", "خطر", "reject", "danger"]
        old = []
        for r in responses.values():
            rl = r.lower()
            pos = sum(1 for w in positive if w in rl)
            neg = sum(1 for w in negative if w in rl)
            old.append("yes" if pos > neg else "no" if neg > pos else "mid")
        return len(set(old)) == 1

    def _judge(self, transcript):
        """الحكم النهائي بناءً على الأحكام الصريحة (fallback كلمي)."""
        scores = {"profiler": 0.5, "analyst": 0.5, "critic": 0.5}
        vmap = {"yes": 0.9, "mid": 0.5, "no": 0.1}

        # اجمع الأحكام الصريحة من كل عضو
        explicit = {}
        for entry in transcript:
            try:
                m = entry.get("member")
                if m not in scores: continue
                v = self._explicit_verdict(entry.get("response", ""))
                if v: explicit[m] = v
            except Exception:
                pass

        if len(explicit) >= 2:
            # استخدم الأحكام الصريحة
            for m, v in explicit.items():
                scores[m] = vmap[v]
            # ═══ أغلبية صريحة 2/3 → قرار حاسم مباشرة ═══
            counts = {}
            for v in explicit.values():
                counts[v] = counts.get(v, 0) + 1
            top = max(counts, key=counts.get)
            if counts[top] >= 2:
                if top == "yes": return "approve", 0.85
                if top == "no":  return "reject", 0.15
                # محايد → human_review
                return "human_review", 0.5
        else:
            # fallback كلمي
            for entry in transcript:
                m = entry.get("member")
                if m not in scores: continue
                r = entry.get("response", "").lower()
                pos = sum(1 for w in ["آمن", "موافق", "مقبول", "safe", "approve"] if w in r)
                neg = sum(1 for w in ["خطر", "مرفوض", "غير آمن", "danger", "reject"] if w in r)
                scores[m] += (pos - neg) * 0.1

        w = JUDGE_CONFIG["weights"]
        final = sum(scores[k] * w[k] for k in scores)
        final = max(0.0, min(1.0, final))

        t = JUDGE_CONFIG["thresholds"]
        if final >= t["approve"]: return "approve", final
        if final <= t["reject"]: return "reject", final
        return "human_review", final
