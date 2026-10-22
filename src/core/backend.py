"""The LLM backend abstraction.

An *agent* never talks to a model directly — it talks to a small ``LLMBackend``
object. That indirection is what makes the whole framework testable offline
(``EchoBackend``) while the real system drives the local ZYVO HTTP API
(:class:`src.core.zyvo_client.ZyvoBackend`).

The interface is intentionally tiny: one synchronous ``generate`` call. Retries,
queues, caching, rate limiting and model fallback live *above* it, composed by
:class:`src.core.resilience.ResilientBackend`, not here.
"""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from src.core.types import Message

__all__ = ["LLMBackend", "EchoBackend", "OllamaBackend"]


@runtime_checkable
class LLMBackend(Protocol):
    """Anything that can turn a list of messages into a text completion."""

    def generate(self, messages: Sequence[Message], *, model: str | None = None) -> str:
        """Return the model's reply for ``messages``.

        ``messages`` is an ordered conversation; a leading ``role="system"``
        message (if present) carries the agent's persona.
        """
        ...  # pragma: no cover - protocol definition


class EchoBackend:
    """Offline backend used by tests and for running without a server.

    It echoes the last message back with a configurable prefix, which makes the
    whole agent/pattern/TUI stack exercisable with zero network and zero ZYVO.
    """

    def __init__(self, prefix: str = "echo: ") -> None:
        self._prefix = prefix

    def generate(self, messages: Sequence[Message], *, model: str | None = None) -> str:
        last = messages[-1].content if messages else ""
        return f"{self._prefix}{last}"


class OllamaBackend:
    """LLMBackend that talks to a local Ollama server (default port 11434)."""

    def __init__(
        self,
        model: str = "sam860/qwen3:1.7b-Q4_K_XL",
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> str:
        import json as _json
        import urllib.request as _urllib

        parts = []
        for m in messages:
            if isinstance(m, Message):
                parts.append(m.role + ": " + m.content)
            elif isinstance(m, dict):
                role = m.get("role", "user")
                content = m.get("content", "")
                parts.append(role + ": " + content)
            else:
                parts.append(str(m))
        prompt = "\n".join(parts)

        payload = _json.dumps({
            "model": model or self.model,
            "prompt": prompt,
            "stream": False,
        }).encode()
        req = _urllib.Request(
            self.base_url + "/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with _urllib.urlopen(req, timeout=self.timeout) as resp:
                data = _json.loads(resp.read())
            return data.get("response", "")
        except Exception as e:
            raise RuntimeError("Ollama request failed: " + str(e)) from e
