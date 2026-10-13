"""
Loop Engine — Recurring agent execution until goal achievement.

Inspired by 2026 agent trends:
- Claude Code's /loop command
- Codex's goal objects
- Cross-run state persistence

Features:
- Run agents repeatedly until success criteria met
- Budget tracking (time, cost)
- State persistence between iterations
- Human-in-the-loop checkpoints
- Graceful termination (max_iterations, budget_exceeded)
"""
import os
import time
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

logger = logging.getLogger("core.loop_engine")


# ═══════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════

@dataclass
class Budget:
    """Budget constraints for the loop."""
    max_time: Optional[float] = None       # seconds
    max_cost: Optional[float] = None       # dollars
    max_iterations: int = 10

    def to_dict(self) -> Dict:
        return {
            "max_time": self.max_time,
            "max_cost": self.max_cost,
            "max_iterations": self.max_iterations,
        }


@dataclass
class Goal:
    """Goal definition."""
    description: str
    success_criteria: Optional[Callable[[Dict], bool]] = None
    max_iterations: int = 10

    def is_success(self, result: Dict) -> bool:
        """Check if result meets success criteria."""
        if self.success_criteria is None:
            # Default: success if "ok" or "success" is True
            return result.get("ok") is True or result.get("success") is True
        try:
            return self.success_criteria(result)
        except Exception as e:
            logger.warning(f"success_criteria raised: {e}")
            return False


@dataclass
class IterationResult:
    """Result of a single iteration."""
    iteration: int
    timestamp: str
    agent_name: str
    result: Dict
    elapsed: float
    success: bool
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class LoopResult:
    """Final result of a loop execution."""
    status: str                    # success | max_iterations | budget_exceeded | error
    iterations: int
    history: List[Dict] = field(default_factory=list)
    final_result: Dict = field(default_factory=dict)
    elapsed: float = 0.0
    total_cost: float = 0.0
    goal: str = ""

    def to_dict(self) -> Dict:
        return {
            "status": self.status,
            "iterations": self.iterations,
            "history": self.history,
            "final_result": self.final_result,
            "elapsed": self.elapsed,
            "total_cost": self.total_cost,
            "goal": self.goal,
        }


# ═══════════════════════════════════════════════════════════
# State persistence
# ═══════════════════════════════════════════════════════════

class StateStore:
    """Persist loop state between runs (for resumption)."""

    def __init__(self, state_dir: Optional[Path] = None):
        base = os.environ.get("NOVAMIND_HOME", str(Path(__file__).resolve().parent.parent))
        self.state_dir = Path(state_dir or (Path(base) / "memory" / "loops"))
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, loop_id: str) -> Path:
        return self.state_dir / f"{loop_id}.json"

    def save(self, loop_id: str, data: Dict) -> None:
        """Save loop state."""
        path = self._path(loop_id)
        try:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        except Exception as e:
            logger.warning(f"failed to save state: {e}")

    def load(self, loop_id: str) -> Optional[Dict]:
        """Load loop state."""
        path = self._path(loop_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"failed to load state: {e}")
            return None

    def delete(self, loop_id: str) -> None:
        """Delete loop state."""
        path = self._path(loop_id)
        if path.exists():
            path.unlink()

    def list_loops(self) -> List[str]:
        """List all saved loop IDs."""
        return [p.stem for p in self.state_dir.glob("*.json")]


# ═══════════════════════════════════════════════════════════
# Loop Engine
# ═══════════════════════════════════════════════════════════

class LoopEngine:
    """
    Execute agents repeatedly until goal is achieved.

    Example:
        engine = LoopEngine()
        goal = Goal(
            description="Fix all failing tests",
            success_criteria=lambda r: r.get("passed") == r.get("total"),
        )
        result = engine.run_until(goal, agent_name="test_runner")
    """

    def __init__(self, factory=None, state_store: Optional[StateStore] = None):
        """
        Args:
            factory: AgentFactory instance (lazy-loaded if None)
            state_store: StateStore for persistence
        """
        self._factory = factory
        self._state_store = state_store or StateStore()

    @property
    def factory(self):
        if self._factory is None:
            from novamind.agents.factory import AgentFactory
            self._factory = AgentFactory()
        return self._factory

    def run_until(
        self,
        goal: Goal,
        agent_name: str,
        agent_kwargs: Optional[Dict] = None,
        budget: Optional[Budget] = None,
        loop_id: Optional[str] = None,
        on_iteration: Optional[Callable[[IterationResult], None]] = None,
        resume: bool = False,
    ) -> LoopResult:
        """
        Run agent repeatedly until goal is achieved.

        Args:
            goal: Goal definition with success criteria
            agent_name: Name of agent to run
            agent_kwargs: Args to pass to agent's main method
            budget: Budget constraints (time, cost, iterations)
            loop_id: Unique ID for persistence (auto-generated if None)
            on_iteration: Callback after each iteration
            resume: If True, resume from saved state

        Returns:
            LoopResult
        """
        agent_kwargs = agent_kwargs or {}
        budget = budget or Budget(max_iterations=goal.max_iterations)
        loop_id = loop_id or self._generate_id(goal.description)

        start_time = time.time()
        history: List[Dict] = []
        iteration = 0

        # Resume from saved state
        if resume:
            saved = self._state_store.load(loop_id)
            if saved:
                iteration = saved.get("iteration", 0)
                history = saved.get("history", [])
                logger.info(f"resumed loop {loop_id} from iteration {iteration}")

        logger.info(f"starting loop {loop_id}: {goal.description[:80]}")

        # Main loop
        while iteration < budget.max_iterations:
            iteration += 1
            iter_start = time.time()

            # Check time budget
            elapsed_total = time.time() - start_time
            if budget.max_time and elapsed_total > budget.max_time:
                return self._build_result(
                    "budget_exceeded", iteration - 1, history,
                    {"error": "time budget exceeded"}, elapsed_total, goal.description,
                )

            # Run agent
            try:
                result = self.factory.call(agent_name, **agent_kwargs)
            except Exception as e:
                logger.exception(f"agent {agent_name} raised")
                result = {"ok": False, "error": str(e)[:200]}

            iter_elapsed = time.time() - iter_start
            success = goal.is_success(result)

            iter_result = IterationResult(
                iteration=iteration,
                timestamp=datetime.now(timezone.utc).isoformat(),
                agent_name=agent_name,
                result=result,
                elapsed=iter_elapsed,
                success=success,
                error=result.get("error") if isinstance(result, dict) and result.get("error") else None,
            )
            history.append(iter_result.to_dict())

            # Callback
            if on_iteration:
                try:
                    on_iteration(iter_result)
                except Exception as e:
                    logger.warning(f"on_iteration callback raised: {e}")

            # Save state
            self._state_store.save(loop_id, {
                "loop_id": loop_id,
                "goal": goal.description,
                "agent_name": agent_name,
                "agent_kwargs": agent_kwargs,
                "iteration": iteration,
                "history": history[-20:],
                "updated_at": iter_result.timestamp,
            })

            logger.info(
                f"iteration {iteration}: success={success} "
                f"elapsed={iter_elapsed:.2f}s"
            )

            # Success?
            if success:
                return self._build_result(
                    "success", iteration, history, result,
                    time.time() - start_time, goal.description,
                )

            # Cost budget?
            total_cost = self._sum_cost(history)
            if budget.max_cost and total_cost > budget.max_cost:
                return self._build_result(
                    "budget_exceeded", iteration, history,
                    {"error": f"cost budget exceeded: ${total_cost:.4f}"},
                    time.time() - start_time, goal.description, total_cost,
                )

        # Max iterations reached
        return self._build_result(
            "max_iterations", iteration, history,
            history[-1]["result"] if history else {},
            time.time() - start_time, goal.description,
        )

    def _build_result(
        self,
        status: str,
        iterations: int,
        history: List[Dict],
        final_result: Dict,
        elapsed: float,
        goal_description: str,
        total_cost: float = 0.0,
    ) -> LoopResult:
        return LoopResult(
            status=status,
            iterations=iterations,
            history=history,
            final_result=final_result,
            elapsed=elapsed,
            total_cost=total_cost,
            goal=goal_description,
        )

    def _sum_cost(self, history: List[Dict]) -> float:
        """Sum cost from history (if agents track cost)."""
        total = 0.0
        for h in history:
            result = h.get("result", {})
            cost = result.get("cost", 0.0) or 0.0
            total += float(cost)
        return total

    def _generate_id(self, goal: str) -> str:
        """Generate a loop ID from goal description."""
        import hashlib
        h = hashlib.md5(goal.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"loop_{ts}_{h}"

    # ═══════════════════════════════════════════════════════
    # Convenience methods
    # ═══════════════════════════════════════════════════════

    def run_simple(
        self,
        description: str,
        agent_name: str,
        agent_kwargs: Optional[Dict] = None,
        max_iterations: int = 10,
    ) -> LoopResult:
        """Simplified API — run until agent reports success."""
        goal = Goal(description=description, max_iterations=max_iterations)
        return self.run_until(goal, agent_name, agent_kwargs=agent_kwargs)

    def resume(self, loop_id: str) -> LoopResult:
        """Resume a previously saved loop."""
        saved = self._state_store.load(loop_id)
        if not saved:
            return LoopResult(
                status="error", iterations=0,
                final_result={"error": f"loop {loop_id} not found"},
                goal="",
            )

        goal = Goal(description=saved.get("goal", ""))
        agent_name = saved.get("agent_name", "")
        agent_kwargs = saved.get("agent_kwargs", {})

        if not agent_name:
            return LoopResult(
                status="error", iterations=0,
                final_result={"error": "saved loop has no agent_name"},
                goal=goal.description,
            )

        return self.run_until(
            goal=goal,
            agent_name=agent_name,
            agent_kwargs=agent_kwargs,
            loop_id=loop_id,
            resume=True,
        )

    def list_loops(self) -> List[str]:
        """List all saved loops."""
        return self._state_store.list_loops()


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════
loop_engine = LoopEngine()


__all__ = [
    "LoopEngine", "loop_engine",
    "Goal", "Budget", "IterationResult", "LoopResult",
    "StateStore",
]
