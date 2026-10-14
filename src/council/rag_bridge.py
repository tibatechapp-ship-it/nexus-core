"""Council + RAG with Cache."""
from __future__ import annotations
import os, sys, json, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from src.council.engine import CouncilEngine, CouncilResult


class CouncilRAGBridge:
    def __init__(self, rag_bridge=None):
        if rag_bridge is None:
            from src.memory.agent_rag_bridge import get_bridge
            rag_bridge = get_bridge()
        self.rag = rag_bridge
        try:
            from novamind.core.llm_router import LLMRouter
            llm = LLMRouter()
        except Exception:
            llm = None
        self.engine = CouncilEngine(llm_router=llm)
        self.history_dir = os.path.expanduser("~/.nexus/data/council")
        os.makedirs(self.history_dir, exist_ok=True)

    def deliberate_with_memory(self, question, context="", use_cache=True):
        # ═══ احفظ الحالة الأصلية قبل RAG ═══
        original_context_empty = not context

        # ═══ CACHE GET ═══
        if use_cache and original_context_empty:
            try:
                from src.council.cache import get_cache
                cached = get_cache().get(question)
                if cached:
                    print("CACHE HIT hits=" + str(cached.hits))
                    return CouncilResult(
                        verdict=cached.verdict, score=cached.score,
                        consensus=cached.score >= 0.7, rounds=cached.rounds,
                        transcript=[{"phase": "cached", "member": "cache",
                                     "response": cached.transcript_summary}],
                        elapsed=0.05, security_events=[],
                    )
            except Exception as e:
                print("CACHE GET ERROR: " + str(e))

        # ═══ RAG ═══
        try:
            docs = self.rag.recall(question, k=5)
            # ═══ فلتر 1: لا قرارات المجلس السابقة (غرفة الصدى) ═══
            docs = [d for d in docs
                    if not (getattr(d, 'text', '') or '').lstrip().startswith('[Council')]
            # ═══ فلتر 2: عتبة التشابه (distance < 1.0 يعني cos > 0.5) ═══
            DISTANCE_THRESHOLD = 1.15
            docs = [d for d in docs
                    if getattr(d, 'distance', 999) < DISTANCE_THRESHOLD]
            if docs:
                mem_ctx = "\n".join("  • " + d.text for d in docs)
                context = (context +
                    "\n\n━━━ معرفة سابقة (مرجعية — ليست حكماً) ━━━\n" +
                    "قد تفيدك هذه المعلومات من محادثات سابقة، لكنها ليست قيوداً." +
                    "\nلك كامل الحرية في مخالفتها إن رأيت حججاً أقوى.\n" +
                    mem_ctx +
                    "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                print("RAG: " + str(len(docs)) + " وثيقة")
        except Exception as e:
            print("RAG ERROR: " + str(e))

        # RECALL PAST SIMILAR DECISIONS (v1.5.3)
        past_hint = ""
        try:
            from src.council.history import get_history
            def _fld(rec, name, default=None):
                if isinstance(rec, dict):
                    return rec.get(name, default)
                return getattr(rec, name, default)
            recent = get_history().list_recent(n=30) or []
            q_words = set(question.lower().split())
            scored = []
            for rec in recent:
                rq = (_fld(rec, "query", "") or "").lower()
                if not rq:
                    continue
                overlap = len(q_words & set(rq.split()))
                if overlap >= 2:
                    scored.append((overlap, rec))
            scored.sort(key=lambda x: -x[0])
            top = scored[:3]
            if top:
                lines = ["== similar past decisions =="]
                for _, rec in top:
                    v = str(_fld(rec, "verdict", "?") or "?").upper()
                    s = float(_fld(rec, "score", 0) or 0)
                    rq = (_fld(rec, "query", "") or "")[:100]
                    lines.append("- %s (%.0f%%): %s" % (v, s*100, rq))
                past_hint = "\n".join(lines)
        except Exception:
            pass

        aug_context = (context + "\n\n" + past_hint).strip() if past_hint else context
        # ═══ DELIBERATE ═══
        result = self.engine.deliberate(question, aug_context)

        # ═══ SAVE TO RAG ═══
        try:
            v = str(result.verdict or "unknown").upper()
            s = float(result.score or 0)
            consensus = " | consensus" if getattr(result, "consensus", False) else ""
            summary = "[Council %s | score=%.0f%%%s] %s" % (v, s*100, consensus, question[:150])
            self.rag.remember(summary)
        except Exception:
            pass

        # ═══ SAVE HISTORY ═══
        try:
            from src.council.history import get_history
            rec_id = get_history().save(result, category="auto", query=question)
            result._record_id = rec_id
        except Exception:
            pass

        # ═══ CACHE SET ═══
        if use_cache and original_context_empty:
            try:
                from src.council.cache import get_cache
                get_cache().set(question, result)
                print("CACHE SAVED: " + question[:40])
            except Exception as e:
                print("CACHE SET ERROR: " + str(e))

        return result



    def deliberate_streaming(self, question, on_event, context="", use_cache=True):
        """نسخة بث حي: تستدعي on_event(event, payload) لحظة إنتاج كل مداخلة."""

        def emit(event, payload):
            try:
                on_event(event, payload)
            except Exception:
                pass

        original_context_empty = not context

        # CACHE GET
        if use_cache and original_context_empty:
            try:
                from src.council.cache import get_cache
                cached = get_cache().get(question)
                if cached:
                    emit("status", {"phase": "cache",
                         "message": "نتيجة من الذاكرة المؤقتة (hits=" + str(getattr(cached, 'hits', '?')) + ")"})
                    emit("agent_action", {"actor": "cache", "phase": "cached",
                         "text": cached.transcript_summary})
                    return CouncilResult(
                        verdict=cached.verdict, score=cached.score,
                        consensus=cached.score >= 0.7, rounds=cached.rounds,
                        transcript=[{"phase": "cached", "member": "cache",
                                     "response": cached.transcript_summary}],
                        elapsed=0.05, security_events=[],
                    )
            except Exception:
                pass

        # RAG
        try:
            docs = self.rag.recall(question, k=5)
            # ═══ فلتر 1: لا قرارات المجلس السابقة (غرفة الصدى) ═══
            docs = [d for d in docs
                    if not (getattr(d, 'text', '') or '').lstrip().startswith('[Council')]
            # ═══ فلتر 2: عتبة التشابه (distance < 1.0 يعني cos > 0.5) ═══
            DISTANCE_THRESHOLD = 1.15
            docs = [d for d in docs
                    if getattr(d, 'distance', 999) < DISTANCE_THRESHOLD]
            if docs:
                mem_ctx = "\n".join("  • " + d.text for d in docs)
                context = (context +
                    "\n\n━━━ معرفة سابقة (مرجعية — ليست حكماً) ━━━\n" +
                    "قد تفيدك هذه المعلومات من محادثات سابقة، لكنها ليست قيوداً." +
                    "\nلك كامل الحرية في مخالفتها إن رأيت حججاً أقوى.\n" +
                    mem_ctx +
                    "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                emit("status", {"phase": "memory", "message": "ذاكرة: " + str(len(docs)) + " وثيقة ذات صلة"})
        except Exception:
            pass

        # DELIBERATE (بث حي)
        result = self.engine.deliberate(question, context, on_event=emit)

        # SAVE TO RAG
        try:
            if result.verdict == "approve":
                self.rag.remember("[Council APPROVED] " + question[:100])
            elif result.verdict == "reject":
                self.rag.remember("[Council REJECTED] " + question[:100])
        except Exception:
            pass

        # SAVE HISTORY (مرة واحدة فقط)
        try:
            from src.council.history import get_history
            rec_id = get_history().save(result, category="web_ui", query=question)
            result._record_id = rec_id
            emit("log", {"message": "تم الحفظ في السجل: " + rec_id})
        except Exception:
            pass

        # CACHE SET
        if use_cache and original_context_empty:
            try:
                from src.council.cache import get_cache
                get_cache().set(question, result)
            except Exception:
                pass

        return result

_bridge = None

def get_council_bridge():
    global _bridge
    if _bridge is None:
        _bridge = CouncilRAGBridge()
    return _bridge
