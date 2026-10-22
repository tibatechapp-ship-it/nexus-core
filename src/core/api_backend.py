"""OpenAI-compatible API backend — use huge cloud models without local RAM.

Works with any provider exposing /chat/completions (OpenAI v1 spec):
- Groq:      https://api.groq.com/openai/v1
- DeepSeek:  https://api.deepseek.com/v1
- OpenRouter: https://openrouter.ai/api/v1
- Together:  https://api.together.xyz/v1
- OpenAI:    https://api.openai.com/v1

Benefits: 30B-405B model quality, zero local RAM, optional tool calling,
and multi-key rotation (extends rate limit on free tiers).

Environment:
    NEXUS_STUDIO_API_URL:  base URL (e.g. https://api.groq.com/openai/v1)
    NEXUS_STUDIO_API_KEYS: one key, or comma-separated for rotation
    NEXUS_STUDIO_MODEL:    model name (e.g. qwen-2.5-coder-32b-instruct)

Same interface as OllamaBackend: generate() + stream().
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any, Sequence

from .types import Message

__all__ = ["APIBackend"]


class APIBackend:
    """OpenAI-compatible HTTP backend with retry + streaming + key rotation."""

    def __init__(
        self,
        base_url: str,
        api_keys: str | list[str],
        model: str,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        if isinstance(api_keys, str):
            keys = [k.strip() for k in api_keys.split(",") if k.strip()]
        else:
            keys = list(api_keys)
        if not keys:
            raise ValueError("At least one API key is required")
        self.api_keys = keys
        self.model = model
        self.timeout = timeout
        self._key_idx = 0

    # ── helpers ─────────────────────────────────────────────────────

    def _next_key(self) -> str:
        key = self.api_keys[self._key_idx % len(self.api_keys)]
        self._key_idx += 1
        return key

    @staticmethod
    def _build_messages(messages: Sequence[Message]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for m in messages:
            if isinstance(m, Message):
                out.append({"role": m.role, "content": m.content})
            elif isinstance(m, dict):
                out.append({
                    "role": m.get("role", "user"),
                    "content": m.get("content", ""),
                })
            else:
                out.append({"role": "user", "content": str(m)})
        return out

    def _make_request(self, payload: dict[str, Any]) -> urllib.request.Request:
        key = self._next_key()
        accept = "text/event-stream" if payload.get("stream") else "application/json"
        return urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
                "Accept": accept,
                "User-Agent": "nexus-core/1.0",  # Cloudflare blocks Python-urllib default
            },
            method="POST",
        )

    # ── public interface ────────────────────────────────────────────

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": self._build_messages(messages),
            "stream": False,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        retryable = (urllib.error.URLError, TimeoutError, OSError)
        try:
            return self._post_once(payload)
        except retryable:
            time.sleep(2.0)
            return self._post_once(payload)

    def _post_once(self, payload: dict[str, Any]) -> str:
        req = self._make_request(payload)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read())
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"API response malformed: {data}") from e

    def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> Iterator[str]:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": self._build_messages(messages),
            "stream": True,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        req = self._make_request(payload)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = obj.get("choices", [{}])[0].get("delta", {})
                    chunk = delta.get("content", "")
                    if chunk:
                        yield chunk
        except Exception as e:
            raise RuntimeError(f"API stream failed: {e}") from e
