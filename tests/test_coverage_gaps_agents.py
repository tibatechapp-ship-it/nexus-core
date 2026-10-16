"""Coverage-gap tests for ``src.agents``.

The one branch the agent suites never reach: a backend that hands the streaming
runner something that is not a string. The runner must reject the piece, mark
the result failed and never crash the caller.
"""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent
from src.agents.state import AgentStatus


class _NonStringBackend:
    """A backend whose ``generate`` returns an int instead of text."""

    def generate(self, messages: Any, *, model: str | None = None) -> Any:
        return 123


class _IntAgent(BaseAgent):
    name = "inty"
    group = "core"


def test_stream_rejects_non_string_pieces() -> None:
    """A non-str piece becomes a failed final chunk (never an exception)."""

    agent = _IntAgent(_NonStringBackend())
    chunks = list(agent.stream("say hi"))

    assert chunks, "the runner must still emit a final chunk"
    final = chunks[-1]
    assert final.final is True
    assert final.error == "backend yielded 'int', expected str"
    assert final.result is not None
    assert final.result.ok is False
    assert agent.state.status == AgentStatus.ERROR
    assert agent.state.last_error == "backend yielded 'int', expected str"
