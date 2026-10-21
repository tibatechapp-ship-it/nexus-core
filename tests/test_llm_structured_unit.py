"""Hermetic unit tests for src/llm/structured.py (no live Ollama needed)."""
import json

import httpx
import pytest

from src.llm.structured import generate_json


SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
}


def _mock_transport(response_body, status_code=200, captured=None):
    def handler(request):
        if captured is not None:
            captured["url"] = str(request.url)
            captured["json"] = json.loads(request.content)
        return httpx.Response(status_code, json=response_body)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_generate_json_returns_parsed_dict(monkeypatch):
    captured = {}
    transport = _mock_transport({"response": json.dumps({"ok": True})}, captured=captured)

    class FakeClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("src.llm.structured.httpx.AsyncClient", FakeClient)
    result = await generate_json("test prompt", SIMPLE_SCHEMA)
    assert result == {"ok": True}
    assert captured["json"]["format"] == SIMPLE_SCHEMA
    assert captured["json"]["stream"] is False


@pytest.mark.asyncio
async def test_generate_json_rejects_malformed_response(monkeypatch):
    transport = _mock_transport({"response": "not json at all"})

    class FakeClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("src.llm.structured.httpx.AsyncClient", FakeClient)
    with pytest.raises(ValueError, match="invalid JSON"):
        await generate_json("prompt", SIMPLE_SCHEMA)


@pytest.mark.asyncio
async def test_generate_json_propagates_http_errors(monkeypatch):
    transport = _mock_transport({"error": "boom"}, status_code=500)

    class FakeClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("src.llm.structured.httpx.AsyncClient", FakeClient)
    with pytest.raises(httpx.HTTPStatusError):
        await generate_json("prompt", SIMPLE_SCHEMA)


@pytest.mark.asyncio
async def test_generate_json_uses_custom_base_url(monkeypatch):
    captured = {}
    transport = _mock_transport({"response": json.dumps({"ok": True})}, captured=captured)

    class FakeClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("src.llm.structured.httpx.AsyncClient", FakeClient)
    await generate_json("p", SIMPLE_SCHEMA, base_url="http://custom:9999/api")
    assert captured["url"].startswith("http://custom:9999/api")
