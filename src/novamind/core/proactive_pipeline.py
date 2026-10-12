"""
Proactive Pipeline — Unified orchestration of security & planning layers.

Flow:
  User Request
     ↓
  [1] Security Gatekeeper (block malicious)
     ↓
  [2] Task Planner (decompose + estimate)
     ↓
  [3] ReAct Loop (execute with tools)
     ↓
  [4] Security Pre-Check (sanitize output)
     ↓
  Final Response
"""
import re
import time
import logging
from typing import Dict, Optional, Callable
from dataclasses import dataclass, field

from novamind.core.security_gatekeeper import gatekeeper
from novamind.core.task_planner import planner
from novamind.core.pre_check import pre_check

logger = logging.getLogger("core.proactive_pipeline")


@dataclass
class PipelineResult:
    status: str              # delivered | blocked | error
    answer: str
    steps: list = field(default_factory=list)
    iterations: int = 0
    elapsed: float = 0.0
    gatekeeper: Optional[Dict] = None
    plan: Optional[Dict] = None
    pre_check: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {
            "status": self.status,
            "answer": self.answer,
            "steps": self.steps,
            "iterations": self.iterations,
            "elapsed": self.elapsed,
            "gatekeeper": self.gatekeeper,
            "plan": self.plan,
            "pre_check": self.pre_check,
        }


class ProactivePipeline:
    """Unified pipeline for proactive agent execution."""

    def __init__(self):
        self._react_loop = None

    def set_react_loop(self, react_loop):
        """Inject ReactLoop after construction."""
        self._react_loop = react_loop

    def execute(self, user_message: str,
                on_event: Optional[Callable[[Dict], None]] = None) -> PipelineResult:
        """Execute the full proactive pipeline."""
        start = time.time()

        # Lazy init ReactLoop if not set (for standalone /api/pipeline/run)
        if self._react_loop is None:
            try:
                from novamind.core.react_loop import ReactLoop
                from novamind.core.llm_router import LLMRouter
                from unified_agent import REACT_TOOLS
                router = LLMRouter()
                self._react_loop = ReactLoop(
                    router=router,
                    tools=REACT_TOOLS,
                    max_iterations=3,
                )
                logger.info("ReactLoop auto-initialized in pipeline")
            except Exception as e:
                logger.warning(f"ReactLoop auto-init failed: {e}")

        def emit(event: Dict):
            if on_event:
                try:
                    on_event(event)
                except Exception as e:
                    logger.warning(f"on_event error: {e}")

        # ═══ [1] Gatekeeper ═══
        emit({"type": "pipeline", "stage": "gatekeeper"})
        gate_verdict = gatekeeper.analyze(user_message)

        if gate_verdict.is_blocked:
            logger.warning(f"Blocked: {gate_verdict.reason}")
            emit({"type": "blocked", "reason": gate_verdict.reason})
            return PipelineResult(
                status="blocked",
                answer=(
                    "⛔ **Request Blocked**\n\n"
                    + gate_verdict.reason + "\n\n"
                    + "_Category: " + gate_verdict.category + "_"
                ),
                elapsed=time.time() - start,
                gatekeeper=gate_verdict.to_dict(),
            )

        # ═══ [2] Planner ═══
        emit({"type": "pipeline", "stage": "planner"})
        plan_dict = None
        try:
            plan = planner.plan(user_message)
            plan_dict = plan.to_dict() if hasattr(plan, "to_dict") else None
            emit({
                "type": "plan",
                "category": getattr(plan, "category", "unknown"),
                "complexity": getattr(plan, "complexity", "unknown"),
                "risk": getattr(plan, "risk_level", "unknown"),
            })
        except Exception as e:
            logger.warning(f"Planner failed: {e}")

        # ═══ [3] Executor (ReAct) ═══
        emit({"type": "pipeline", "stage": "executor"})
        if self._react_loop is None:
            return PipelineResult(
                status="error",
                answer="Pipeline error: ReactLoop not initialized",
                elapsed=time.time() - start,
                gatekeeper=gate_verdict.to_dict(),
                plan=plan_dict,
            )

        try:
            react_result = self._react_loop.run(user_message, on_event=on_event)
        except Exception as e:
            logger.error(f"ReAct failed: {e}")
            return PipelineResult(
                status="error",
                answer="Execution error: " + str(e),
                elapsed=time.time() - start,
                gatekeeper=gate_verdict.to_dict(),
                plan=plan_dict,
            )

        answer = react_result.get("answer", "")
        steps = react_result.get("steps", [])

        # ═══ [4] Pre-Check ═══
        emit({"type": "pipeline", "stage": "pre_check"})
        pre_dict = None

        if answer and "```" in answer:
            code_blocks = re.findall(r'```(?:\w+)?\n([\s\S]+?)```', answer)
            if code_blocks:
                full_code = "\n".join(code_blocks)
                pre_result = pre_check.check(full_code)
                pre_dict = pre_result.to_dict()

                if pre_result.decision == "block":
                    emit({"type": "blocked", "reason": "pre_check"})
                    return PipelineResult(
                        status="blocked",
                        answer=(
                            "⛔ **Code Blocked by Pre-Check**\n\n"
                            + pre_check.explain(pre_result)
                        ),
                        steps=steps,
                        elapsed=time.time() - start,
                        gatekeeper=gate_verdict.to_dict(),
                        plan=plan_dict,
                        pre_check=pre_dict,
                    )
                elif pre_result.decision == "auto_fixed":
                    fixed_code = pre_result.final_code
                    answer = re.sub(
                        r'```(?:\w+)?\n[\s\S]+?```',
                        "```python\n" + fixed_code + "\n```",
                        answer,
                        count=1,
                    )
                    answer += "\n\n" + pre_check.explain(pre_result)
                    emit({"type": "auto_fixed", "count": pre_result.auto_fixes_applied})
                elif pre_result.decision == "warn":
                    answer += "\n\n⚠️ **Security Warnings:**\n" + pre_check.explain(pre_result)

        # ═══ [5] Success ═══
        status = "delivered"
        if pre_dict and pre_dict.get("decision") == "auto_fixed":
            status = "delivered_fixed"
        elif pre_dict and pre_dict.get("decision") == "warn":
            status = "delivered_warned"

        return PipelineResult(
            status=status,
            answer=answer,
            steps=steps,
            iterations=react_result.get("iterations", 0),
            elapsed=time.time() - start,
            gatekeeper=gate_verdict.to_dict(),
            plan=plan_dict,
            pre_check=pre_dict,
        )


pipeline = ProactivePipeline()



# ═══════════════════════════════════════════════════════
# Global instance (singleton)
# ═══════════════════════════════════════════════════════
proactive_pipeline = ProactivePipeline()

__all__ = ["ProactivePipeline", "PipelineResult", "pipeline", "proactive_pipeline"]
