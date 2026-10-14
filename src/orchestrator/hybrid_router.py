"""Hybrid Router — يوجّه بين Smart Router / Agent Loop / Council."""
from __future__ import annotations
import os
import sys
import re
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))


# ═══ أنماط التصنيف ═══
PATTERNS = {
    "tool": [
        r"\b(احفظ|ذكر|سجّل|remember|save)\b",
        r"\b(ابحث في الذاكرة|search_memory|recall)\b",
        r"\b(اعرض ملفات|list_files|ls\b)",
        r"\b(اقرأ ملف|read_file|cat\s)",
        r"\b(اكتب ملف|write_file|create\s+file)\b",
        r"\b(الوقت|التاريخ|time|date|now)\b",
        r"\b(شغّل أمر|run_shell|نفذ|execute)\b",
        r"\b(اعرض|اظهر|أرني|show|display)\b.*\b(ملفات|مجلد|files|folder|directory)\b",
    ],
    "decision": [
        r"\b(أم|أيهما|compare|vs\b|which|أي أفضل|مقارنة|الفرق بين)\b",
        r"\b(هل نستخدم|should we|نختار|choose)\b",
        r"\b(قرار|decision|decide)\b",
    ],
    "code": [
        r"\b(اكتب دالة|اكتب كود|اكتب كلاس|write function|write code)\b",
        r"\b(أصلح|صلح|fix|debug|repair)\b",
        r"\b(راجع|review|audit)\b",
        r"\b(أعد هيكلة|refactor|optimize)\b",
        r"\b(اختبر|test|pytest|unit test)\b",
        r"\b(python|javascript|java|code|function|class|script)\b",
    ],
    "security": [
        r"\b(ثغرة|ثغرات|اختراق|vulnerability|exploit|attack)\b",
        r"\b(أمني|أمنية|security|secure)\b",
        r"\b(production|prod)\b",
    ],
}


def classify(prompt: str) -> str:
    """يصنف الطلب: tool / decision / code / general."""
    text = prompt.lower()
    scores = {k: 0 for k in PATTERNS}

    for cat, pats in PATTERNS.items():
        for p in pats:
            if re.search(p, text, re.IGNORECASE):
                scores[cat] += 1

    # ═══ الأولوية ═══
    # 1. security + decision → council
    if scores["security"] > 0 and scores["decision"] > 0:
        return "decision"

    # 2. tool (لو تحقق)
    if scores["tool"] > 0:
        # لكن إذا فيه code قوي (2+) → code
        if scores["code"] >= 2:
            return "code"
        return "tool"

    # 3. decision
    if scores["decision"] > 0:
        return "decision"

    # 4. code
    if scores["code"] > 0:
        return "code"

    # 5. أمان
    if scores["security"] > 0:
        return "decision"

    # 6. افتراضي = tool (Agent Loop يتعامل مع العام)
    return "tool"


class HybridRouter:
    """يوجّه الطلب للطريقة المثلى."""

    def __init__(self, use_rag=True, verbose=False):
        self.use_rag = use_rag
        self.verbose = verbose

    def run(self, prompt: str, force: str = None) -> dict:
        """ينفذ الطلب بالطريقة المثلى."""
        route = force or classify(prompt)

        if self.verbose:
            print(f"🧭 Hybrid Router → {route}")

        t0 = time.time()

        if route == "code":
            result = self._run_smart(prompt)
        elif route == "decision":
            result = self._run_council(prompt)
        else:  # tool
            result = self._run_loop(prompt)

        result["route"] = route
        result["total_elapsed"] = round(time.time() - t0, 2)
        return result

    def _run_smart(self, prompt: str) -> dict:
        """Smart Router + Supervisor."""
        try:
            from src.orchestrator.supervisor import Supervisor
            sup = Supervisor(use_rag=self.use_rag, verbose=False)
            r = sup.execute(prompt)
            return {
                "ok": r.get("ok", False),
                "method": "smart_router",
                "decision": r.get("decision", {}),
                "results": [
                    {
                        "agent": x.get("agent", "?"),
                        "ok": x.get("ok", False),
                        "elapsed": x.get("elapsed", 0),
                        "result": str(x.get("result", ""))[:1500],
                        "error": x.get("error", ""),
                    }
                    for x in r.get("results", [])
                ],
                "answer": self._build_smart_answer(r),
            }
        except Exception as e:
            return {"ok": False, "method": "smart_router", "error": str(e)}

    def _run_loop(self, prompt: str) -> dict:
        """Agent Loop (ReAct)."""
        try:
            from src.agent_loop.loop import AgentLoop
            loop = AgentLoop(max_iterations=8, verbose=self.verbose)
            r = loop.run(prompt)
            return {
                "ok": r.get("ok", False),
                "method": "agent_loop",
                "iterations": r.get("iterations", 0),
                "trace": r.get("trace", []),
                "answer": r.get("answer", ""),
                "error": r.get("error", ""),
            }
        except Exception as e:
            return {"ok": False, "method": "agent_loop", "error": str(e)}

    def _run_council(self, prompt: str) -> dict:
        """Council of Agents."""
        try:
            import src.nexus
            from src.council.rag_bridge import get_council_bridge
            b = get_council_bridge()
            b.engine.MAX_ROUNDS = 1
            r = b.deliberate_with_memory(prompt)
            return {
                "ok": r.verdict != "reject",
                "method": "council",
                "verdict": r.verdict,
                "score": r.score,
                "rounds": r.rounds,
                "elapsed": r.elapsed,
                "transcript": [
                    {"phase": e["phase"], "member": e["member"],
                     "response": e["response"][:500]}
                    for e in r.transcript
                ],
                "answer": f"القرار: {r.verdict} ({r.score:.2f})",
            }
        except Exception as e:
            return {"ok": False, "method": "council", "error": str(e)}

    def _build_smart_answer(self, r: dict) -> str:
        """يبني إجابة موحدة من Smart Router."""
        results = r.get("results", [])
        if not results:
            return ""
        parts = []
        for x in results:
            if x.get("ok") and x.get("result"):
                parts.append(str(x["result"]))
            elif x.get("error"):
                parts.append(f"خطأ: {x['error'][:100]}")
        return "\n\n".join(parts)[:2000]


# Singleton
_router = None

def get_hybrid_router(use_rag=True, verbose=False) -> HybridRouter:
    global _router
    if _router is None or _router.use_rag != use_rag:
        _router = HybridRouter(use_rag=use_rag, verbose=verbose)
    return _router
