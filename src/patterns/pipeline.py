"""Pipeline pattern — each agent's output becomes the next one's context."""

from __future__ import annotations

from collections.abc import Iterable

from src.agents.base import BaseAgent
from src.core.types import AgentResult
from src.patterns._stage import run_stage
from src.patterns.checkpoint import CheckpointStore, StageCheckpoint
from src.tools.executor import ToolPolicy, ToolRun

__all__ = ["Pipeline"]


class Pipeline:
    """Runs agents in order, chaining each output into the next as context.

    Pass a :class:`~src.patterns.checkpoint.CheckpointStore` and a ``run_id`` to
    *resume* an interrupted run: stages already finished successfully are skipped
    and their saved output is reused, so a crash costs only the work still
    pending. Without a store (or without ``run_id``) behaviour is unchanged.
    """

    def __init__(
        self,
        agents: Iterable[BaseAgent],
        *,
        tools: ToolPolicy | None = None,
        checkpoints: CheckpointStore | None = None,
    ) -> None:
        self._agents = list(agents)
        if not self._agents:
            raise ValueError("Pipeline needs at least one agent")
        self._tools = tools
        self._checkpoints = checkpoints
        #: Tool traces from the most recent :meth:`run` (empty without a policy).
        self.tool_runs: list[ToolRun] = []
        #: The ``run_id`` of the most recent :meth:`run` (``None`` when unset).
        self.run_id: str | None = None

    def run(self, task: str, *, run_id: str | None = None) -> AgentResult:
        """Run the chain and return the final agent's result.

        The chain stops early (returning the failed result) as soon as one
        stage fails. With a checkpoint store and ``run_id``, a stage that already
        succeeded in a previous run is reused instead of re-executed.
        """
        self.tool_runs = []
        self.run_id = run_id
        resuming = run_id is not None and self._checkpoints is not None
        context = ""
        result: AgentResult | None = None
        for index, agent in enumerate(self._agents):
            if resuming:
                assert run_id is not None and self._checkpoints is not None  # noqa: S101
                saved = self._checkpoints.completed_stage(run_id, index)
                if saved is not None:
                    result = AgentResult(
                        agent=saved.agent,
                        ok=True,
                        output=saved.output,
                        duration_s=saved.duration_s,
                    )
                    context = result.output
                    continue
            outcome = run_stage(agent, task, context=context, tools=self._tools)
            if outcome.tool_run is not None:
                self.tool_runs.append(outcome.tool_run)
            result = outcome.result
            if resuming:
                self._save(run_id, index, result)
            if not result.ok:
                return result
            context = result.output
        assert result is not None  # guarded by the constructor
        return result

    def _save(self, run_id: str | None, index: int, result: AgentResult) -> None:
        """Record one finished stage so a future resume can skip it."""
        if run_id is None or self._checkpoints is None:
            return
        self._checkpoints.save(
            StageCheckpoint(
                run_id=run_id,
                stage=index,
                agent=result.agent,
                ok=result.ok,
                output=result.output,
                error=result.error,
                duration_s=result.duration_s,
            )
        )
