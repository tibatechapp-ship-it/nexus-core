"""Tests for src/core/ollama_backend.py — Ollama Cloud backend with key rotation."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest

import src.core.ollama_backend as ob
from src.core.ollama_backend import OllamaBackend, OllamaError


class _FakeResp:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload


def _ok_payload(text: str = "hello") -> bytes:
    return json.dumps({"choices": [{"message": {"content": text}}]}).encode("utf-8")


# ─────────────────────────── __init__ / keys ───────────────────────────

def test_init_requires_keys(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import src.core.ollama_backend as mod

    monkeypatch.setattr(mod.Path, "home", classmethod(lambda cls: tmp_path / "empty"))
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    with pytest.raises(OllamaError):
        OllamaBackend(keys=[])


def test_init_with_explicit_keys_and_models() -> None:
    b = OllamaBackend(keys=["k1", "k2"], model="m0")
    assert b.keys == ["k1", "k2"]
    assert b.models[0] == "m0"
    assert b.models == list(dict.fromkeys(b.models))  # deduped, ordered


def test_dedupe_preserves_order() -> None:
    assert OllamaBackend._dedupe(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_load_keys_from_active2_and_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    active2 = home / ".config" / "zyvo" / "keys" / "active-2"
    active2.mkdir(parents=True)
    good = "a" * 55
    (active2 / "01.key").write_text(good, encoding="utf-8")
    (active2 / "02.key").write_text("tooshort", encoding="utf-8")  # rejected (<50)
    (active2 / "03.key").write_text(good, encoding="utf-8")  # duplicate → skipped
    monkeypatch.setattr(ob.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("OLLAMA_API_KEY", "e" * 52)
    keys = OllamaBackend._load_keys()
    assert keys == [good, "e" * 52]


def test_load_keys_no_dir_no_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ob.Path, "home", classmethod(lambda cls: tmp_path / "empty"))
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    assert OllamaBackend._load_keys() == []


# ─────────────────────────────── _call ───────────────────────────────

def test_call_success_and_message_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    b = OllamaBackend(keys=["k"])
    monkeypatch.setattr(ob.urllib.request, "urlopen", lambda req, timeout: _FakeResp(_ok_payload("hi")))
    # objects with .role/.content, dicts, and raw strings all supported
    class M:
        role = "user"
        content = "c"

    assert b._call("k", "m", [M(), {"role": "user", "content": "d"}, "raw"]) == "hi"


def test_call_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    b = OllamaBackend(keys=["k"])

    def raise_http(req: Any, timeout: float) -> Any:
        raise urllib.error.HTTPError("http://x", 429, "rate limited", {}, io.BytesIO(b"slow down"))

    monkeypatch.setattr(ob.urllib.request, "urlopen", raise_http)
    with pytest.raises(OllamaError) as exc:
        b._call("k", "m", [])
    assert "429" in str(exc.value)


def test_call_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    b = OllamaBackend(keys=["k"])

    def raise_url(req: Any, timeout: float) -> Any:
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(ob.urllib.request, "urlopen", raise_url)
    with pytest.raises(OllamaError):
        b._call("k", "m", [])


def test_call_bad_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    b = OllamaBackend(keys=["k"])
    monkeypatch.setattr(ob.urllib.request, "urlopen", lambda req, timeout: _FakeResp(b'{"nope": 1}'))
    with pytest.raises(OllamaError):
        b._call("k", "m", [])


# ─────────────────────────────── generate ───────────────────────────────

def test_generate_first_try_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    b = OllamaBackend(keys=["k1"], model="m")
    monkeypatch.setattr(b, "_call", lambda key, model, messages, max_tokens=2000: "ok")
    assert b.generate([]) == "ok"


def test_generate_rotates_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    b = OllamaBackend(keys=["k1", "k2"], model="m")
    calls = {"n": 0}

    def flaky(key: str, model: str, messages: Any, max_tokens: int = 2000) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise OllamaError("429 rate limit")
        return "recovered"

    monkeypatch.setattr(b, "_call", flaky)
    assert b.generate([]) == "recovered"


def test_generate_exhausts_and_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    b = OllamaBackend(keys=["k1"], model="m")

    def always_fail(key: str, model: str, messages: Any, max_tokens: int = 2000) -> str:
        raise OllamaError("nope")

    monkeypatch.setattr(b, "_call", always_fail)
    with pytest.raises(OllamaError) as exc:
        b.generate([])
    assert "فشلت كل المحاولات" in str(exc.value)
