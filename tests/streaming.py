"""Streaming generation — observing a model's answer as it is produced.

The base :mod:`src.core.backend` contract is a single synchronous ``generate``
call: simple, and enough for the whole framework to run offline. But a real
console wants to paint tokens as they arrive. This module adds an **opt-in**
streaming seam without touching that contract:

* :class:`StreamingBackend` — a protocol for backends that can yield a reply in
  pieces (``stream(...) -> Iterator[str]``).
* :func:`iter_stream` — adapts *any* backend to a chunk iterator: a streaming
  backend yields its pieces; a plain one yields the single ``generate`` result as
  one chunk. So streaming never breaks a non-streaming backend.
* :class:`EchoStreamingBackend` — an offline streaming backend for tests/demos.
* :class:`StreamChunk` — one piece of a streamed answer (with the final chunk
  carrying the assembled :class:`~src.core.types.AgentResult`).

:meth:`src.agents.base.BaseAgent.stream` is the agent-side entry point; it never
raises, records metrics exactly like :meth:`BaseAgent.run`, and stays byte-for-
byte compatible when the backend does not stream.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from src.core.backend import LLMBackend
from src.core.types import AgentResult, Message

__all__ = [
    "EchoStreamingBackend",
    "StreamChunk",
    "StreamingBackend",
    "collect_stream",
    "iter_stream",
]


@runtime_checkable
class StreamingBackend(Protocol):
    """A backend that can produce its reply incrementally."""

    def stream(
        self, messages: Sequence[Message], *, model: str | None = None
    ) -> Iterator[str]:
        """Yield the reply for ``messages`` in one or more text pieces."""
        ...  # pragma: no cover - protocol definition


@dataclass(frozen=True, slots=True)
class StreamChunk:
    """One piece of a streamed agent answer.

    The last chunk of a stream has ``final=True`` and always carries the
    assembled :class:`~src.core.types.AgentResult` (ok or error) in ``result``.
    """

    agent: str
    index: int
    delta: str = ""
    final: bool = False
    error: str | None = None
    result: AgentResult | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view."""
        return {
            "agent": self.agent,
            "index": self.index,
            "delta": self.delta,
            "final": self.final,
            "error": self.error,
            "result": self.result.as_dict() if self.result is not None else None,
        }


def iter_stream(
    backend: object,
    messages: Sequence[Message],
    *,
    model: str | None = None,
) -> Iterator[str]:
    """Yield ``backend``'s reply in pieces, from a streaming or plain backend.

    A :class:`StreamingBackend` is asked to ``stream``; anything else is called
    with its one-shot ``generate`` and the whole reply is yielded as one chunk.
    """
    if isinstance(backend, StreamingBackend):
        yield from backend.stream(messages, model=model)
        return
    if not hasattr(backend, "generate"):
        raise TypeError(f"{type(backend).__name__!r} is not a usable LLM backend")
    yield cast(LLMBackend, backend).generate(messages, model=model)


def collect_stream(chunks: Iterator[StreamChunk]) -> tuple[str, AgentResult | None]:
    """Consume ``chunks`` and return ``(joined_text, final_result)``.

    ``final_result`` is ``None`` only if the stream produced no final chunk.
    """
    text: list[str] = []
    result: AgentResult | None = None
    for chunk in chunks:
        text.append(chunk.delta)
        if chunk.final:
            result = chunk.result
    return "".join(text), result


class EchoStreamingBackend:
    """Offline backend that echoes the last message back in fixed-size chunks.

    Doubles as both a plain backend (``generate``) and a streaming one
    (``stream``), which makes the whole streaming path exercisable with zero
    network — exactly like :class:`~src.core.backend.EchoBackend`.
    """

    def __init__(self, prefix: str = "echo: ", *, chunk_size: int = 8) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size must be >= 1")
        self._prefix = prefix
        self.chunk_size = chunk_size

    def generate(self, messages: Sequence[Message], *, model: str | None = None) -> str:
        """Return the full echoed reply (also the concatenation of ``stream``)."""
        last = messages[-1].content if messages else ""
        return f"{self._prefix}{last}"

    def stream(
        self, messages: Sequence[Message], *, model: str | None = None
    ) -> Iterator[str]:
        """Yield the echoed reply in ``chunk_size`` pieces."""
        text = self.generate(messages, model=model)
        for start in range(0, len(text), self.chunk_size):
            yield text[start : start + self.chunk_size]
