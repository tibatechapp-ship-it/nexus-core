"""Unit tests for OllamaBackend.stream — no network required (mocked urlopen)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest

from src.core.backend import OllamaBackend
from src.core.types import Message


class _FakeResponse:
    """Mimics the urllib response object: iterable of bytes lines, context manager."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __iter__(self) -> Iterator[bytes]:
        return iter(self._lines)

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


def _ndjson(*pieces: str, done: bool = True) -> list[bytes]:
    """Build Ollama-style NDJSON lines (one JSON object per line)."""
    out: list[bytes] = []
    for piece in pieces:
        out.append((json.dumps({"response": piece, "done": False}) + "\n").encode())
    if done:
        out.append((json.dumps({"response": "", "done": True}) + "\n").encode())
    return out


def _backend() -> OllamaBackend:
    return OllamaBackend(model="test-model", base_url="http://test:11434", timeout=5.0)


def test_stream_yields_each_piece() -> None:
    backend = _backend()
    fake = _FakeResponse(_ndjson("Hello", " ", "world"))
    with patch("urllib.request.urlopen", return_value=fake):
        pieces = list(backend.stream([Message("user", "hi")]))
    assert pieces == ["Hello", " ", "world"]


def test_stream_joins_to_full_reply() -> None:
    backend = _backend()
    fake = _FakeResponse(_ndjson("abc", "def", "ghi"))
    with patch("urllib.request.urlopen", return_value=fake):
        joined = "".join(backend.stream([Message("user", "x")]))
    assert joined == "abcdefghi"


def test_stream_stops_at_done() -> None:
    backend = _backend()
    lines = _ndjson("first", "second", done=False)
    lines.append((json.dumps({"response": "third", "done": True}) + "\n").encode())
    lines.append((json.dumps({"response": "should-not-appear"}) + "\n").encode())
    fake = _FakeResponse(lines)
    with patch("urllib.request.urlopen", return_value=fake):
        pieces = list(backend.stream([Message("user", "x")]))
    assert pieces == ["first", "second", "third"]


def test_stream_skips_empty_lines() -> None:
    backend = _backend()
    lines = [b"\n"] + _ndjson("only") + [b"   \n"]
    fake = _FakeResponse(lines)
    with patch("urllib.request.urlopen", return_value=fake):
        pieces = list(backend.stream([Message("user", "x")]))
    assert pieces == ["only"]


def test_stream_skips_empty_response_fields() -> None:
    backend = _backend()
    lines = [
        (json.dumps({"response": ""}) + "\n").encode(),
        (json.dumps({"response": "x"}) + "\n").encode(),
        (json.dumps({"response": "y", "done": True}) + "\n").encode(),
    ]
    fake = _FakeResponse(lines)
    with patch("urllib.request.urlopen", return_value=fake):
        pieces = list(backend.stream([Message("user", "x")]))
    assert pieces == ["x", "y"]


def test_stream_builds_correct_payload() -> None:
    backend = _backend()
    fake = _FakeResponse(_ndjson("ok"))
    captured: list[Any] = []

    def _capture(req: Any, timeout: float) -> _FakeResponse:
        captured.append((req, timeout))
        return fake

    with patch("urllib.request.urlopen", side_effect=_capture):
        list(backend.stream([Message("user", "hello")], model="override"))

    assert captured, "urlopen not called"
    req, timeout = captured[0]
    payload = json.loads(req.data)
    assert payload["model"] == "override"
    assert payload["stream"] is True
    assert "user: hello" in payload["prompt"]
    assert timeout == 5.0


def test_stream_raises_runtime_on_network_error() -> None:
    backend = _backend()

    def _boom(req: Any, timeout: float) -> _FakeResponse:
        raise OSError("connection refused")

    with patch("urllib.request.urlopen", side_effect=_boom), pytest.raises(
        RuntimeError, match="Ollama stream failed"
    ):
        list(backend.stream([Message("user", "x")]))


def test_stream_accepts_dicts_and_strings() -> None:
    backend = _backend()
    fake = _FakeResponse(_ndjson("ok"))
    seen: list[dict[str, Any]] = []

    def _capture(req: Any, timeout: float) -> _FakeResponse:
        seen.append(json.loads(req.data))
        return fake

    with patch("urllib.request.urlopen", side_effect=_capture):
        list(backend.stream([{"role": "user", "content": "hi"}, "raw"]))

    prompt = seen[0]["prompt"]
    assert "user: hi" in prompt
    assert "raw" in prompt


def test_stream_satisfies_streaming_backend_protocol() -> None:
    from src.core.streaming import StreamingBackend

    assert isinstance(_backend(), StreamingBackend)


def test_iter_stream_uses_ollama_stream() -> None:
    """iter_stream must prefer OllamaBackend.stream() over generate()."""
    from src.core.streaming import iter_stream

    backend = _backend()
    fake = _FakeResponse(_ndjson("a", "b", "c"))
    with patch("urllib.request.urlopen", return_value=fake):
        pieces = list(iter_stream(backend, [Message("user", "x")]))
    assert pieces == ["a", "b", "c"]
