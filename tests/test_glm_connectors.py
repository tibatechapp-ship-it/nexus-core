"""GLM connector tests — M1.3 / M1.4 acceptance suite.

Hermetic: no external network — every HTTP case runs against a localhost
mock server that mimics the OpenAI-compatible chat-completions contract,
and every env touch goes through ``monkeypatch`` so tests stay
order-independent. 28 cases cover the local connector, the cloud
connector, the failover wrapper and the BYOK factory integration.
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

import pytest

from connectors.base import BaseConnector
from connectors.glm_cloud import GlmCloudConnector, GlmFailoverConnector
from connectors.glm_local import GlmLocalConnector
from hyper_app.services.llm_factory import create_llm_client_from_request

# ── hermetic env: no GLM/ZAI variable leaks in from the developer machine ──

_GLM_ENV_VARS = ("GLM_LOCAL_URL", "GLM_MODEL", "GLM_CLOUD_BASE", "GLM_CLOUD_MODEL",
                 "ZAI_API_KEY", "ZAI_TOKEN")


@pytest.fixture(autouse=True)
def _clean_glm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _GLM_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


# ── localhost mock server (OpenAI-compatible, behaviour driven per test) ───


def _ok_body(reply: str = "mock-reply") -> dict[str, Any]:
    return {"choices": [{"message": {"role": "assistant", "content": reply}}]}


class _MockGLMServer:
    """Threaded localhost server; tests mutate ``status``/``body``/``raw_body``."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.status = 200
        self.body: dict[str, Any] | None = None
        self.raw_body: str | None = None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._make_handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1/chat/completions"

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 — stdlib dispatch name
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                try:
                    payload = json.loads(raw)
                except Exception:
                    payload = {"_raw": raw.decode("utf-8", "replace")}
                outer.requests.append(
                    {"path": self.path, "payload": payload, "headers": dict(self.headers)}
                )
                text = outer.raw_body if outer.raw_body is not None else json.dumps(
                    outer.body if outer.body is not None else _ok_body()
                )
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(text.encode())))
                self.end_headers()
                self.wfile.write(text.encode())

            def log_message(self, *args: Any) -> None:
                pass  # keep pytest output clean

        return Handler

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def mock_glm() -> Callable[[], _MockGLMServer]:
    servers: list[_MockGLMServer] = []

    def make() -> _MockGLMServer:
        s = _MockGLMServer()
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.stop()


def _closed_port() -> int:
    """A loopback port that refuses connections (bound then released)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ── GlmLocalConnector ───────────────────────────────────────────────────────


def test_local_default_model() -> None:
    assert GlmLocalConnector().model == "zai-org/GLM-5.3"


def test_local_default_endpoint_is_local_vllm() -> None:
    assert GlmLocalConnector()._endpoint() == "http://127.0.0.1:8000/v1/chat/completions"


async def test_local_env_endpoint_override(mock_glm: Callable[[], _MockGLMServer]) -> None:
    server = mock_glm()
    server.status = 200
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GLM_LOCAL_URL", server.url)
        res = await GlmLocalConnector().generate("ping")
    assert res == {"ok": True, "reply": "mock-reply"}
    assert server.requests[0]["path"] == "/v1/chat/completions"


async def test_local_env_model_override(mock_glm: Callable[[], _MockGLMServer]) -> None:
    server = mock_glm()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GLM_MODEL", "zai-org/GLM-5.3-AWQ")
        mp.setenv("GLM_LOCAL_URL", server.url)
        connector = GlmLocalConnector()
        await connector.generate("ping")
    assert server.requests[0]["payload"]["model"] == "zai-org/GLM-5.3-AWQ"


def test_local_constructor_model_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLM_MODEL", "env-model")
    assert GlmLocalConnector(model="ctor-model").model == "ctor-model"


async def test_local_constructor_key_sets_bearer(mock_glm: Callable[[], _MockGLMServer]) -> None:
    server = mock_glm()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GLM_LOCAL_URL", server.url)
        await GlmLocalConnector(api_key="ctor-key").generate("ping")
    auth = server.requests[0]["headers"].get("Authorization")
    assert auth == "Bearer ctor-key"


async def test_local_zai_api_key_env_sets_bearer(
    mock_glm: Callable[[], _MockGLMServer], monkeypatch: pytest.MonkeyPatch
) -> None:
    server = mock_glm()
    monkeypatch.setenv("ZAI_API_KEY", "env-key")
    monkeypatch.setenv("GLM_LOCAL_URL", server.url)
    await GlmLocalConnector().generate("ping")
    assert server.requests[0]["headers"].get("Authorization") == "Bearer env-key"


async def test_local_zai_token_env_is_the_fallback_slot(
    mock_glm: Callable[[], _MockGLMServer], monkeypatch: pytest.MonkeyPatch
) -> None:
    server = mock_glm()
    monkeypatch.setenv("ZAI_TOKEN", "plan-slot-key")
    monkeypatch.setenv("GLM_LOCAL_URL", server.url)
    await GlmLocalConnector().generate("ping")
    assert server.requests[0]["headers"].get("Authorization") == "Bearer plan-slot-key"


async def test_local_no_key_omits_auth_header(mock_glm: Callable[[], _MockGLMServer]) -> None:
    server = mock_glm()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GLM_LOCAL_URL", server.url)
        await GlmLocalConnector().generate("ping")
    assert "Authorization" not in server.requests[0]["headers"]


async def test_local_generate_returns_reply(mock_glm: Callable[[], _MockGLMServer]) -> None:
    server = mock_glm()
    server.body = _ok_body("hello from glm")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GLM_LOCAL_URL", server.url)
        res = await GlmLocalConnector().generate("hi")
    assert res == {"ok": True, "reply": "hello from glm"}


async def test_local_system_prompt_becomes_system_message(
    mock_glm: Callable[[], _MockGLMServer],
) -> None:
    server = mock_glm()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GLM_LOCAL_URL", server.url)
        await GlmLocalConnector().generate("user text", system_prompt="be terse")
    messages = server.requests[0]["payload"]["messages"]
    assert messages[0] == {"role": "system", "content": "be terse"}
    assert messages[1] == {"role": "user", "content": "user text"}


async def test_local_empty_system_prompt_omits_system_message(
    mock_glm: Callable[[], _MockGLMServer],
) -> None:
    server = mock_glm()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GLM_LOCAL_URL", server.url)
        await GlmLocalConnector().generate("user text")
    roles = [m["role"] for m in server.requests[0]["payload"]["messages"]]
    assert roles == ["user"]


async def test_local_payload_matches_plan_constants(
    mock_glm: Callable[[], _MockGLMServer],
) -> None:
    server = mock_glm()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GLM_LOCAL_URL", server.url)
        await GlmLocalConnector().generate("ping")
    payload = server.requests[0]["payload"]
    assert payload["temperature"] == 0.2
    assert payload["max_tokens"] == 8192


async def test_local_server_error_maps_to_ok_false(mock_glm: Callable[[], _MockGLMServer]) -> None:
    server = mock_glm()
    server.status = 500
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GLM_LOCAL_URL", server.url)
        res = await GlmLocalConnector().generate("ping")
    assert res["ok"] is False
    assert "500" in res["error"]


async def test_local_connection_refused_maps_to_ok_false() -> None:
    url = f"http://127.0.0.1:{_closed_port()}/v1/chat/completions"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GLM_LOCAL_URL", url)
        res = await GlmLocalConnector().generate("ping")
    assert res["ok"] is False
    assert len(res["error"]) <= 200


async def test_local_malformed_json_maps_to_ok_false(mock_glm: Callable[[], _MockGLMServer]) -> None:
    server = mock_glm()
    server.raw_body = "this is not json"
    res = await GlmLocalConnector().generate("ping")
    assert res["ok"] is False


def test_factory_builds_glm_local() -> None:
    client = create_llm_client_from_request({"provider": "glm-local", "model": "zai-org/GLM-5.3"})
    assert isinstance(client, GlmLocalConnector)
    assert isinstance(client, BaseConnector)


# ── GlmCloudConnector ───────────────────────────────────────────────────────


def test_cloud_default_model() -> None:
    assert GlmCloudConnector().model == "glm-5.3"


def test_cloud_default_endpoint() -> None:
    assert GlmCloudConnector()._endpoint() == "https://api.z.ai/api/paas/v4/chat/completions"


def test_cloud_env_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLM_CLOUD_MODEL", "glm-5.3-flash")
    assert GlmCloudConnector().model == "glm-5.3-flash"


def test_cloud_base_ending_with_endpoint_not_doubled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLM_CLOUD_BASE", "https://proxy.example/v4/chat/completions/")
    assert GlmCloudConnector()._endpoint() == "https://proxy.example/v4/chat/completions"


async def test_cloud_missing_key_fails_fast_without_request(
    mock_glm: Callable[[], _MockGLMServer],
) -> None:
    server = mock_glm()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GLM_CLOUD_BASE", server.url)
        res = await GlmCloudConnector().generate("ping")
    assert res == {"ok": False, "error": "Missing Z.AI API key"}
    assert server.requests == []


async def test_cloud_success_roundtrip(mock_glm: Callable[[], _MockGLMServer]) -> None:
    server = mock_glm()
    server.body = _ok_body("cloud reply")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GLM_CLOUD_BASE", server.url)
        mp.setenv("ZAI_API_KEY", "env-cloud-key")
        res = await GlmCloudConnector().generate("ping")
    assert res == {"ok": True, "reply": "cloud reply"}
    assert server.requests[0]["headers"]["Authorization"] == "Bearer env-cloud-key"


async def test_cloud_error_maps_to_ok_false(mock_glm: Callable[[], _MockGLMServer]) -> None:
    server = mock_glm()
    server.status = 429
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GLM_CLOUD_BASE", server.url)
        mp.setenv("ZAI_API_KEY", "k")
        res = await GlmCloudConnector().generate("ping")
    assert res["ok"] is False


# ── GlmFailoverConnector (M1.4) ─────────────────────────────────────────────


async def test_failover_prefers_local_when_healthy(
    mock_glm: Callable[[], _MockGLMServer],
) -> None:
    local, cloud = mock_glm(), mock_glm()
    conn = GlmFailoverConnector(
        local=GlmLocalConnector(),
        cloud=GlmCloudConnector(api_key="k"),
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GLM_LOCAL_URL", local.url)
        mp.setenv("GLM_CLOUD_BASE", cloud.url)
        res = await conn.generate("ping")
    assert res == {"ok": True, "reply": "mock-reply"}
    assert conn.last_backend == "local"
    assert cloud.requests == []  # cloud never contacted


async def test_failover_switches_to_cloud_when_local_down(
    mock_glm: Callable[[], _MockGLMServer],
) -> None:
    cloud = mock_glm()
    down = f"http://127.0.0.1:{_closed_port()}/v1/chat/completions"
    conn = GlmFailoverConnector(
        local=GlmLocalConnector(),
        cloud=GlmCloudConnector(api_key="k"),
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GLM_LOCAL_URL", down)
        mp.setenv("GLM_CLOUD_BASE", cloud.url)
        res = await conn.generate("ping")
    assert res["ok"] is True
    assert res["failover"] is True
    assert conn.last_backend == "cloud"
    assert len(cloud.requests) == 1


async def test_failover_returns_to_local_automatically(
    mock_glm: Callable[[], _MockGLMServer],
) -> None:
    """Kill the local server, let one call ride the cloud, then watch it come back."""
    local, cloud = mock_glm(), mock_glm()
    local.status = 500  # local "down" (failing), cloud healthy
    conn = GlmFailoverConnector(
        local=GlmLocalConnector(),
        cloud=GlmCloudConnector(api_key="k"),
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GLM_LOCAL_URL", local.url)
        mp.setenv("GLM_CLOUD_BASE", cloud.url)
        first = await conn.generate("ping")
        assert first["failover"] is True
        local.status = 200  # local heals — next call must use it again
        second = await conn.generate("ping")
    assert second == {"ok": True, "reply": "mock-reply"}
    assert "failover" not in second
    assert conn.last_backend == "local"


async def test_failover_both_down_reports_combined_error(
    mock_glm: Callable[[], _MockGLMServer],
) -> None:
    cloud = mock_glm()
    cloud.status = 503
    down = f"http://127.0.0.1:{_closed_port()}/v1/chat/completions"
    conn = GlmFailoverConnector(
        local=GlmLocalConnector(),
        cloud=GlmCloudConnector(api_key="k"),
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GLM_LOCAL_URL", down)
        mp.setenv("GLM_CLOUD_BASE", cloud.url)
        res = await conn.generate("ping")
    assert res["ok"] is False
    assert res["error"].startswith("local:")
    assert "cloud:" in res["error"]
    assert conn.last_backend == "none"


async def test_failover_via_factory_registers_contract(
    mock_glm: Callable[[], _MockGLMServer],
) -> None:
    server = mock_glm()
    client = create_llm_client_from_request({"provider": "glm"})
    assert isinstance(client, GlmFailoverConnector)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GLM_LOCAL_URL", server.url)
        res = await client.generate("ping")
    assert res["ok"] is True
