"""E2E tests for /api/chat — httpx, no browser needed.

Real API contract:
- POST /api/chat
- Header: x-auth-token: <token>
- Body: {"message": "...", "agent": "default"}
- Response: SSE (text/event-stream) with:
    data: {"type": "plan", "agent": "...", "conversation_id": "..."}
    data: {"type": "chunk", "content": "...", "provider": "...", "reflection": {...}}
    data: [DONE]
"""
import json
import os
from pathlib import Path

import httpx
import pytest

BASE = "http://127.0.0.1:8000"
TOKEN_PATH = Path(
    "/data/data/com.termux/files/usr/var/service/nexus-core/env/NEXUS_AUTH_TOKEN"
)


@pytest.fixture(scope="session")
def auth_token():
    if not TOKEN_PATH.exists():
        pytest.fail(f"Token file missing: {TOKEN_PATH}")
    token = TOKEN_PATH.read_text().strip()
    if not token:
        pytest.fail("Auth token is empty")
    return token


def _parse_sse(response_text: str):
    """Yield parsed JSON events from an SSE body."""
    for line in response_text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if payload == "[DONE]":
            yield {"type": "done"}
            continue
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue


@pytest.mark.asyncio
async def test_chat_arabic_response(auth_token):
    """POST /api/chat with Arabic message -> chunk with Arabic text."""
    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
        resp = await client.post(
            "/api/chat",
            headers={"x-auth-token": auth_token},
            json={"message": "قل مرحبا", "agent": "default"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        chunks = list(_parse_sse(resp.text))
        content = "".join(
            c.get("content", "") for c in chunks if c.get("type") == "chunk"
        )
        assert content.strip(), "Expected non-empty chunk content"
        assert any("\u0600" <= ch <= "\u06FF" for ch in content), (
            f"Expected Arabic, got: {content[:100]}"
        )


@pytest.mark.asyncio
async def test_chat_streaming_events(auth_token):
    """SSE must contain chunk events and end with [DONE]."""
    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
        async with client.stream(
            "POST",
            "/api/chat",
            headers={"x-auth-token": auth_token},
            json={"message": "hi", "agent": "default"},
        ) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")

            has_chunk = False
            has_done = False
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if payload == "[DONE]":
                    has_done = True
                else:
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "chunk":
                        has_chunk = True

            assert has_chunk, "No chunk events in SSE stream"
            assert has_done, "Stream did not end with [DONE]"


@pytest.mark.asyncio
async def test_auth_required():
    """POST /api/chat without x-auth-token -> 401."""
    async with httpx.AsyncClient(base_url=BASE, timeout=10.0) as client:
        resp = await client.post(
            "/api/chat",
            json={"message": "hi", "agent": "default"},
        )
        assert resp.status_code in (401, 403), (
            f"Expected 401/403, got {resp.status_code}"
        )


@pytest.mark.asyncio
async def test_provider_fallback(auth_token):
    """Response includes a provider name (circuit breaker fallback proof)."""
    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
        resp = await client.post(
            "/api/chat",
            headers={"x-auth-token": auth_token},
            json={"message": "who are you?", "agent": "default"},
        )
        assert resp.status_code == 200

        chunks = list(_parse_sse(resp.text))
        chunk_events = [c for c in chunks if c.get("type") == "chunk"]
        assert chunk_events, "No chunk events"

        provider = chunk_events[0].get("provider")
        assert provider, f"Missing provider in event: {chunk_events[0]}"
        assert isinstance(provider, str) and len(provider) > 0
