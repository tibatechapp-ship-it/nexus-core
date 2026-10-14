"""Council + RAG — كل مداولة تُثري الذاكرة."""
from __future__ import annotations
import os, sys, json, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from src.council.engine import CouncilEngine


class CouncilRAGBridge:
    def __init__(self, rag_bridge=None):
        if rag_bridge is None:
            from src.memory.agent_rag_bridge import get_bridge
            rag_bridge = get_bridge()
        self.rag = rag_bridge
        # ═══ إنشاء engine مع LLM ═══
        try:
            from novamind.core.llm_router import LLMRouter
            llm = LLMRouter()
        except Exception:
            llm = None
        self.engine = CouncilEngine(llm_router=llm)
        self.history_dir = os.path.expanduser("~/.nexus/data/council")
        os.makedirs(self.history_dir, exist_ok=True)

    def deliberate_with_memory(self, question, context=""):
        # استرجاع
        try:
            docs = self.rag.recall(question, k=5)
            if docs:
                mem_ctx = "\n".join(f"  • [{d.id}] {d.text}" for d in docs)
                context = f"{context}\n\n━━━ ذاكرة سابقة ━━━\n{mem_ctx}"
                print(f"🧠 استرجع {len(docs)} وثيقة")
        except Exception as e:
            print(f"⚠️ RAG: {e}")
        # مداولة
        result = self.engine.deliberate(question, context)
        # حفظ
        try:
            if result.verdict == "approve":
                self.rag.remember(f"[Council APPROVED] {question[:100]}: score={result.score:.2f}")
            elif result.verdict == "reject":
                self.rag.remember(f"[Council REJECTED] {question[:100]}: score={result.score:.2f}")
        except Exception:
            pass
        # سجل
        log_id = f"council_{int(time.time())}"
        try:
            with open(os.path.join(self.history_dir, f"{log_id}.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "question": question, "verdict": result.verdict, "score": result.score,
                    "rounds": result.rounds, "transcript": result.transcript,
                    "security_events": result.security_events,
                }, f, ensure_ascii=False, indent=2, default=str)
        except Exception:
            pass
        return result


_bridge = None

def get_council_bridge():
    global _bridge
    if _bridge is None:
        _bridge = CouncilRAGBridge()
    return _bridge
