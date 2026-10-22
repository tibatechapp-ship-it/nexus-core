"""Tests for src.core.api_backend — OpenAI-compatible backend (mocked, no network)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest

from src.core.api_backend import APIBackend
from src.core.types import Message


# ── fakes ──────────────────────────────────────────────────────────

class _FakeResp:
    """Mimics urllib response for non-streaming (read) and streaming (iter)."""

    def __init__(self, payload: dict[str, Any] | None = None, lines: list[bytes] | None = None):
        self._payload = payload
        self._lines = lines or []

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload or {}).encode()

    def __iter__(self) -> Iterator[bytes]:
        return iter(self._lines)


def _backend(**kw: Any) -> APIBackend:
    defaults = {
        "base_url": "https://api.test.com/v1",
        "api_keys": "sk-test-1",
        "model": "test-model",
        "timeout": 5.0,
    }
    defaults.update(kw)
    return APIBackend(**defaults)


# ── constructor ────────────────────────────────────────────────────

def test_requires_at_least_one_key() -> None:
    with pytest.raises(ValueError, match="At least one"):
        APIBackend(base_url="https://x.com/v1", api_keys="", model="m")


def test_accepts_single_key_string() -> None:
    b = _backend(api_keys="sk-one")
    assert b.api_keys == ["sk-one"]


def test_accepts_comma_separated_keys() -> None:
    b = _backend(api_keys="sk-1, sk-2 ,sk-3")
    assert b.api_keys == ["sk-1", "sk-2", "sk-3"]


def test_accepts_list_of_keys() -> None:
    b = _backend(api_keys=["sk-a", "sk-b"])
    assert b.api_keys == ["sk-a", "sk-b"]


def test_key_rotation_cycles() -> None:
    b = _backend(api_keys="sk-1,sk-2")
    assert b._next_key() == "sk-1"
    assert b._next_key() == "sk-2"
    assert b._next_key() == "sk-1"  # cycles


# ── _build_messages ────────────────────────────────────────────────

def test_build_messages_handles_message_dict_str() -> None:
    msgs = [
        Message("system", "sys"),
        {"role": "user", "content": "hi"},
        "raw string",
    ]
    out = APIBackend._build_messages(msgs)
    assert out == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "user", "content": "raw string"},
    ]


# ── generate ───────────────────────────────────────────────────────

def test_generate_returns_content() -> None:
    fake = _FakeResp(payload={
        "choices": [{"message": {"content": "def f(): pass"}}],
    })
    b = _backend()
    with patch("urllib.request.urlopen", return_value=fake):
        out = b.generate([Message("user", "hi")])
    assert out == "def f(): pass"


def test_generate_retries_once_on_network_error() -> None:
    import urllib.error
    calls = {"n": 0}

    def _fake(req: Any, timeout: float) -> _FakeResp:
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("temporary")
        return _FakeResp(payload={"choices": [{"message": {"content": "OK"}}]})

    b = _backend()
    with patch("urllib.request.urlopen", side_effect=_fake), patch("time.sleep"):
        out = b.generate([Message("user", "hi")])
    assert out == "OK"
    assert calls["n"] == 2


def test_generate_includes_tools_in_payload() -> None:
    captured: list[Any] = []

    def _fake(req: Any, timeout: float) -> _FakeResp:
        captured.append(json.loads(req.data))
        return _FakeResp(payload={"choices": [{"message": {"content": "x"}}]})

    b = _backend()
    tools = [{"type": "function", "function": {"name": "read_file"}}]
    with patch("urllib.request.urlopen", side_effect=_fake):
        b.generate([Message("user", "hi")], tools=tools)

    payload = captured[0]
    assert payload["tools"] == tools
    assert payload["tool_choice"] == "auto"
    assert payload["stream"] is False


def test_generate_raises_on_malformed_response() -> None:
    fake = _FakeResp(payload={"unexpected": "shape"})
    b = _backend()
    with patch("urllib.request.urlopen", return_value=fake), \
         pytest.raises(RuntimeError, match="malformed"):
        b.generate([Message("user", "hi")])


# ── stream ─────────────────────────────────────────────────────────

def test_stream_yields_chunks_and_stops_at_done() -> None:
    lines = [
        b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n',
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n',
        b'data: [DONE]\n',
        b'data: {"choices":[{"delta":{"content":"ignored"}}]}\n',
    ]
    fake = _FakeResp(lines=lines)
    b = _backend()
    with patch("urllib.request.urlopen", return_value=fake):
        pieces = list(b.stream([Message("user", "hi")]))
    assert pieces == ["Hel", "lo"]


def test_stream_ignores_non_data_lines() -> None:
    lines = [
        b":comment\n",
        b"event: ping\n",
        b'data: {"choices":[{"delta":{"content":"X"}}]}\n',
        b'data: [DONE]\n',
    ]
    fake = _FakeResp(lines=lines)
    b = _backend()
    with patch("urllib.request.urlopen", return_value=fake):
        pieces = list(b.stream([Message("user", "hi")]))
    assert pieces == ["X"]
