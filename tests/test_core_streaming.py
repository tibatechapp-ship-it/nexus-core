"""Tests for src.core.streaming — the streaming backend seam and BaseAgent.stream."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from src.agents.base import BaseAgent
from src.core.backend import EchoBackend
from src.core.streaming import (
    EchoStreamingBackend,
    StreamChunk,
    StreamingBackend,
    collect_stream,
    iter_stream,
)
from src.core.types import Message


class _RaisingBackend:
    """A plain (non-streaming) backend that always raises."""

    def generate(self, messages: Sequence[Message], *, model: str | None = None) -> str:
        raise RuntimeError("boom")


class _RaisingStreamBackend(EchoStreamingBackend):
    """A streaming backend that blows up mid-stream."""

    def stream(
        self, messages: Sequence[Message], *, model: str | None = None
    ) -> Iterator[str]:
        yield "partial "
        raise RuntimeError("stream boom")


class _RecordingStreamBackend:
    """A streaming backend that records the messages it was given."""

    def __init__(self, chunks: tuple[str, ...]) -> None:
        self.chunks = chunks
        self.seen: list[list[Message]] = []

    def stream(
        self, messages: Sequence[Message], *, model: str | None = None
    ) -> Iterator[str]:
        self.seen.append(list(messages))
        yield from self.chunks


def _agent(backend: object) -> BaseAgent:
    agent = BaseAgent(backend)  # type: ignore[arg-type]
    agent.name = "streamer"
    return agent


# ── StreamChunk ───────────────────────────────────────────────────────────
def test_stream_chunk_defaults_and_to_dict() -> None:
    chunk = StreamChunk(agent="a", index=0, delta="hi")
    assert chunk.final is False
    assert chunk.error is None
    assert chunk.result is None
    data = chunk.to_dict()
    assert data["agent"] == "a" and data["delta"] == "hi" and data["result"] is None


def test_stream_chunk_to_dict_with_result() -> None:
    from src.core.types import AgentResult

    chunk = StreamChunk(
        agent="a", index=1, final=True, result=AgentResult(agent="a", ok=True, output="x")
    )
    data = chunk.to_dict()
    assert data["final"] is True
    assert data["result"] == {
        "agent": "a",
        "ok": True,
        "output": "x",
        "error": None,
        "duration_s": 0.0,
    }


# ── iter_stream ───────────────────────────────────────────────────────────
def test_iter_stream_plain_backend_yields_one_chunk() -> None:
    chunks = list(iter_stream(EchoBackend(prefix="r: "), [Message("user", "hi")]))
    assert chunks == ["r: hi"]


def test_iter_stream_streaming_backend_yields_pieces() -> None:
    pieces = list(iter_stream(EchoStreamingBackend(prefix="abc", chunk_size=2), [Message("user", "x")]))
    assert pieces == ["ab", "cx"]  # "abcx" in 2-char pieces


def test_iter_stream_pieces_join_to_full_reply() -> None:
    messages = [Message("user", "hello world")]
    joined = "".join(iter_stream(EchoStreamingBackend(prefix=">> ", chunk_size=3), messages))
    assert joined == ">> hello world"


def test_echo_streaming_backend_chunk_size_must_be_positive() -> None:
    with pytest.raises(ValueError):
        EchoStreamingBackend(chunk_size=0)


def test_echo_streaming_backend_empty_reply_streams_nothing() -> None:
    # An empty reply yields zero chunks (the agent stream still ends with a final).
    pieces = list(EchoStreamingBackend(prefix="").stream([Message("user", "")]))
    assert pieces == []


# ── collect_stream ────────────────────────────────────────────────────────
def test_collect_stream_joins_and_keeps_final_result() -> None:
    from src.core.types import AgentResult

    chunks = [
        StreamChunk(agent="a", index=0, delta="one "),
        StreamChunk(agent="a", index=1, delta="two"),
        StreamChunk(
            agent="a", index=2, final=True, result=AgentResult(agent="a", ok=True, output="one two")
        ),
    ]
    text, result = collect_stream(iter(chunks))
    assert text == "one two"
    assert result is not None and result.ok


def test_collect_stream_without_final_returns_none_result() -> None:
    text, result = collect_stream(iter([StreamChunk(agent="a", index=0, delta="x")]))
    assert text == "x"
    assert result is None


# ── BaseAgent.stream ──────────────────────────────────────────────────────
def test_stream_with_streaming_backend_joins_and_marks_metrics() -> None:
    backend = EchoStreamingBackend(prefix="r: ", chunk_size=2)
    agent = _agent(backend)

    chunks = list(agent.stream("hi"))
    text = "".join(c.delta for c in chunks)
    final = chunks[-1]

    assert text == "r: hi"
    assert final.final is True and final.result is not None and final.result.ok
    assert final.result.output == "r: hi"
    assert agent.metrics.tasks_run == 1
    assert agent.state.to_dict()["status"] == "idle"


def test_stream_with_plain_backend_is_single_chunk_plus_final() -> None:
    agent = _agent(EchoBackend(prefix="e: "))
    chunks = list(agent.stream("hi"))
    assert [c.delta for c in chunks] == ["e: hi", ""]
    assert chunks[-1].final and chunks[-1].result is not None
    assert chunks[-1].result.output == "e: hi"


def test_stream_folds_context_and_lessons_into_user_turn() -> None:
    backend = _RecordingStreamBackend(("answer",))
    agent = _agent(backend)
    list(agent.stream("task", context="ctx", lessons="never give up"))
    user_turn = backend.seen[0][-1].content
    assert "task" in user_turn
    assert "--- context ---" in user_turn and "ctx" in user_turn
    assert "--- lessons ---" in user_turn and "never give up" in user_turn


def test_stream_failure_delivers_error_final_chunk() -> None:
    agent = _agent(_RaisingBackend())
    chunks = list(agent.stream("boom"))
    final = chunks[-1]
    assert final.final is True and final.error == "boom"
    assert final.result is not None and not final.result.ok
    assert final.result.error == "boom"
    assert agent.metrics.tasks_run == 1
    assert agent.state.to_dict()["status"] == "error"


def test_stream_midway_failure_keeps_partial_output() -> None:
    agent = _agent(_RaisingStreamBackend())
    text, result = collect_stream(agent.stream("t"))
    assert text == "partial "
    assert result is not None and not result.ok
    assert result.error == "stream boom"


def test_stream_runs_twice_do_not_leak_state() -> None:
    agent = _agent(EchoStreamingBackend(prefix="x", chunk_size=2))
    first = list(agent.stream("a"))
    second = list(agent.stream("b"))
    assert "".join(c.delta for c in first) == "xa"
    assert "".join(c.delta for c in second) == "xb"
    assert agent.metrics.tasks_run == 2
    assert agent.state.to_dict()["status"] == "idle"


def test_streaming_backend_is_runtime_detectable() -> None:
    assert isinstance(EchoStreamingBackend(), StreamingBackend)
    assert not isinstance(EchoBackend(), StreamingBackend)