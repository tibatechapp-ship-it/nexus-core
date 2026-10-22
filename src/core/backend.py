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

from collections.abc import Iterator
from typing import Protocol, Sequence, runtime_checkable, Any

from src.core.types import Message

# ─── URL safety: only allow http/https (blocks file://, ftp://, etc.) ───
def _safe_urlopen(req: Any, *, timeout: float) -> Any:
    """Open a URL request, rejecting anything but http:// or https://."""
    import urllib.request as _urllib
    url = req.full_url if hasattr(req, "full_url") else str(req)
    if not (url.startswith("http://") or url.startswith("https://")):
        raise PermissionError(f"unsafe URL scheme (only http/https allowed): {url[:60]}")
    return _urllib.urlopen(req, timeout=timeout)

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
        timeout: float = 180.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @staticmethod
    def _build_prompt(messages: Sequence[Message]) -> str:
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
        return "\n".join(parts)

    def _generate_once(
        self,
        messages: Sequence[Message],
        *,
        model: str | None,
    ) -> str:
        import json as _json
        import urllib.request as _urllib

        payload = _json.dumps({
            "model": model or self.model,
            "prompt": self._build_prompt(messages),
            "stream": False,
            "think": False,
        }).encode()
        req = _urllib.Request(
            self.base_url + "/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _safe_urlopen(req, timeout=self.timeout) as resp:
            data = _json.loads(resp.read())
        return data.get("response", "")

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> str:
        """One-shot reply; retries once on timeout/connection error.

        A single retry covers the common transient case: the local model is
        still loading, or the phone briefly starved the process. Network-level
        and timeout failures are exactly the class that a retry can fix.
        Bad-request / model-not-found errors are not retried, since a second
        identical call would fail identically.
        """
        import time as _time
        import urllib.error as _urlerror

        retryable = (_urlerror.URLError, TimeoutError, OSError)
        try:
            return self._generate_once(messages, model=model)
        except retryable as first:
            _time.sleep(2.0)
            try:
                return self._generate_once(messages, model=model)
            except Exception as second:
                raise RuntimeError(
                    "Ollama request failed after retry: "
                    + str(first)
                    + " / "
                    + str(second)
                ) from second
        except Exception as e:
            raise RuntimeError("Ollama request failed: " + str(e)) from e

    def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> Iterator[str]:
        """Yield the reply from Ollama incrementally (NDJSON, one JSON per line).

        Mirrors :meth:`generate` but sets ``"stream": true`` and reads the
        response line-by-line, yielding each ``response`` field as it arrives.
        Satisfies :class:`~src.core.streaming.StreamingBackend`, so
        :func:`~src.core.streaming.iter_stream` will use it automatically.
        """
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
            "stream": True,
            "think": False,
        }).encode()
        req = _urllib.Request(
            self.base_url + "/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with _safe_urlopen(req, timeout=self.timeout) as resp:
                for raw in resp:
                    line = raw.strip()
                    if not line:
                        continue
                    obj = _json.loads(line)
                    piece = obj.get("response", "")
                    if piece:
                        yield piece
                    if obj.get("done"):
                        return
        except Exception as e:
            raise RuntimeError("Ollama stream failed: " + str(e)) from e
