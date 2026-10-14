"""Loop + RAG Bridge — حلقات ذكية تُثري الذاكرة وتتعلم منها.

يدمج:
- LoopEngine (التنفيذ المتكرر حتى تحقيق الهدف)
- AgentRAGBridge (الذاكرة الدلالية)

النتيجة: نظام ذاتي التعلم على مستوى الحلقات.
"""
from __future__ import annotations
import os
import sys
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Callable, Any

logger = logging.getLogger("loop_rag_bridge")

# ═══ Path setup ═══
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))


@dataclass
class LoopMemoryEntry:
    """مدخل ذاكرة من حلقة."""
    iteration: int
    agent: str
    prompt: str
    result: str
    success: bool
    elapsed: float
    context_used: List[str] = field(default_factory=list)


class LoopRAGBridge:
    """جسر Loop + RAG — كل حلقة تُثري الذاكرة."""

    def __init__(self, rag_bridge=None, state_dir: str = None):
        """
        Args:
            rag_bridge: AgentRAGBridge instance (optional — يُنشأ تلقائياً)
            state_dir: مجلد حفظ الحالة
        """
        if rag_bridge is None:
            from src.memory.agent_rag_bridge import get_bridge
            rag_bridge = get_bridge()
        self.rag = rag_bridge
        self.state_dir = state_dir or os.path.expanduser("~/.nexus/data/loops")
        os.makedirs(self.state_dir, exist_ok=True)

    def run_with_memory(
        self,
        goal: str,
        agent_name: str,
        agent_method: str = "build",
        max_iterations: int = 5,
        success_criteria: Optional[Callable[[Dict], bool]] = None,
        enrich_context: bool = True,
        save_success: bool = True,
    ) -> Dict:
        """تشغيل حلقة ذكية مع RAG.

        Args:
            goal: وصف الهدف
            agent_name: اسم الوكيل (مثل "coder")
            agent_method: الطريقة (build/run/analyze)
            max_iterations: الحد الأقصى للدورات
            success_criteria: دالة تتحقق من النجاح
            enrich_context: هل نُثري prompts بالسياق؟
            save_success: هل نحفظ النتائج الناجحة؟

        Returns:
            dict يحتوي: status, iterations, history, final_result
        """
        history: List[LoopMemoryEntry] = []
        start_time = time.time()
        last_result: Dict = {}
        final_status = "max_iterations"

        # تحميل الوكيل
        from nova.registry import REGISTRY
        try:
            agent = REGISTRY.load_agent(agent_name)
        except Exception as e:
            return {
                "status": "error",
                "error": f"فشل تحميل الوكيل {agent_name}: {e}",
                "iterations": 0,
                "history": [],
            }

        # كشف الطريقة
        if not hasattr(agent, agent_method):
            for m in ["build", "run", "execute", "analyze", "fix", "review", "generate"]:
                if hasattr(agent, m):
                    agent_method = m
                    break
            else:
                return {
                    "status": "error",
                    "error": f"الوكيل {agent_name} لا يملك طريقة قابلة للتنفيذ",
                    "iterations": 0,
                    "history": [],
                }

        # ═══ الحلقة ═══
        for iteration in range(1, max_iterations + 1):
            iter_start = time.time()
            iter_prompt = goal

            # 1. إثراء بالسياق من الذاكرة
            contexts_used = []
            if enrich_context:
                try:
                    docs = self.rag.recall(goal, k=3)
                    if docs:
                        context = "\n".join(f"  • {d.text}" for d in docs)
                        iter_prompt = f"""{goal}

━━━ سياق من الحلقات السابقة ━━━
{context}
━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
                        contexts_used = [d.text[:50] for d in docs]
                except Exception as e:
                    logger.warning(f"RAG enrich failed: {e}")

            # 2. تنفيذ الوكيل
            print(f"🔄 دورة {iteration}/{max_iterations}: {agent_name}.{agent_method}")
            try:
                result = getattr(agent, agent_method)(iter_prompt)
            except Exception as e:
                result = {"ok": False, "error": str(e)}

            elapsed = time.time() - iter_start

            # 3. تحديد النجاح
            if success_criteria:
                try:
                    success = success_criteria(result)
                except Exception:
                    success = False
            else:
                success = result.get("ok") is True or result.get("success") is True

            # 4. تسجيل النتيجة
            entry = LoopMemoryEntry(
                iteration=iteration,
                agent=agent_name,
                prompt=goal,
                result=str(result)[:500],
                success=success,
                elapsed=elapsed,
                context_used=contexts_used,
            )
            history.append(entry)
            last_result = result

            # 5. حفظ في الذاكرة
            if save_success and success:
                try:
                    text = result.get("code") or result.get("text") or str(result)[:300]
                    self.rag.remember(f"[Loop {agent_name}] {goal}: {text[:200]}")
                except Exception as e:
                    logger.warning(f"Save failed: {e}")

            # 6. فحص النجاح
            if success:
                final_status = "success"
                print(f"✅ تحقق الهدف في الدورة {iteration}")
                break

            # إضافة تأخير بسيط
            time.sleep(0.1)

        total_elapsed = time.time() - start_time

        # ═══ حفظ حالة الحلقة ═══
        loop_id = f"loop_{int(start_time)}"
        self._save_state(loop_id, {
            "goal": goal,
            "agent": agent_name,
            "method": agent_method,
            "status": final_status,
            "iterations": len(history),
            "elapsed": total_elapsed,
            "history": [h.__dict__ for h in history],
        })

        return {
            "status": final_status,
            "iterations": len(history),
            "elapsed": total_elapsed,
            "final_result": last_result,
            "history": [h.__dict__ for h in history],
            "loop_id": loop_id,
        }

    def _save_state(self, loop_id: str, data: Dict) -> None:
        """يحفظ حالة الحلقة."""
        import json
        path = os.path.join(self.state_dir, f"{loop_id}.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        except Exception as e:
            logger.warning(f"State save failed: {e}")

    def get_learning_stats(self) -> Dict:
        """إحصائيات التعلم عبر كل الحلقات."""
        import json
        loops = []
        for fname in os.listdir(self.state_dir):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(self.state_dir, fname), encoding="utf-8") as f:
                        loops.append(json.load(f))
                except Exception:
                    pass

        if not loops:
            return {"total_loops": 0, "success_rate": 0.0}

        success = sum(1 for l in loops if l.get("status") == "success")
        total_iters = sum(l.get("iterations", 0) for l in loops)
        return {
            "total_loops": len(loops),
            "successful": success,
            "success_rate": success / len(loops),
            "total_iterations": total_iters,
            "avg_iterations": total_iters / len(loops),
        }


_bridge = None

def get_loop_bridge() -> LoopRAGBridge:
    """Singleton."""
    global _bridge
    if _bridge is None:
        _bridge = LoopRAGBridge()
    return _bridge
