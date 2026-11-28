"""P1 runtime guards: content-free audit, strict allowlists and bounded waits."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from novamind.core.llm_router import DEFAULT_TIMEOUT, LLMRouter, ProviderConfig
from novamind.factory import llm_wrapper
from src.agent_loop.loop import AgentLoop
from src.agent_loop.tools import build_default_registry
from src.mcp.external import (
    AuditEvent,
    ExternalMCPClient,
    ExternalMCPError,
    ExternalServerConfig,
    safe_child_env,
    sanitize_audit_tool,
)
from src.orchestrator.smart_router import RouteDecision
import src.orchestrator.supervisor as supervisor_mod


# ── 1. external MCP audit + allowlist ───────────────────────────────────────


def _config(**kwargs: Any) -> ExternalServerConfig:
    return ExternalServerConfig(
        name="unit",
        command=(sys.executable, "-c", "pass"),
        env=safe_child_env(),
        tool_namespace="unit",
        **kwargs,
    )


def test_audit_event_sanitizes_untrusted_tool_name() -> None:
    event = AuditEvent(
        server="unit",
        tool="echo?token=very-secret\nassistant",
        ok=False,
        duration_ms=0,
        chars=0,
        error_code=-32001,
    )
    assert sanitize_audit_tool("echo") == "echo"
    assert event.tool == "<invalid>"
    assert "very-secret" not in str(event.to_dict())


def test_rejected_tool_name_is_never_dispatched_or_leaked_to_audit() -> None:
    client = ExternalMCPClient(
        _config(allowed_tools=frozenset({"echo"})),
        on_audit=lambda event: events.append(event.to_dict()),
    )
    events: list[dict[str, Any]] = []
    try:
        with pytest.raises(ExternalMCPError) as rejected:
            client.call_tool("unit.echo;token=very-secret", {})
        assert rejected.value.code == -32602
        assert len(events) == 1
        assert events[0]["tool"] == "<invalid>"
        assert "very-secret" not in str(events[0])
    finally:
        client.close()


def test_none_allowlist_is_constrained_to_discovered_schemas() -> None:
    client = ExternalMCPClient(_config())
    try:
        assert client._permitted_tool_names() == frozenset()
        client._schemas = {"echo": {"name": "echo", "inputSchema": {"type": "object"}}}
        assert client._permitted_tool_names() == frozenset({"echo"})
        client._ensure_ready = lambda: None  # type: ignore[method-assign]

        events: list[dict[str, Any]] = []
        client.on_audit = lambda event: events.append(event.to_dict())
        with pytest.raises(ExternalMCPError) as unknown:
            client.call_tool("unit.ghost", {})
        assert unknown.value.code == -32601
        assert events[0]["tool"] == "ghost"
    finally:
        client.close()


# ── 2. LLM router/wrapper availability contract ─────────────────────────────


def _router(*names: str) -> LLMRouter:
    router = LLMRouter()
    router.providers = [
        ProviderConfig(
            name=name,
            api_key="unit-test-key",
            base_url="",
            models={"fast": f"{name}-fast", "smart": f"{name}-smart"},
            priority=index,
        )
        for index, name in enumerate(names, 1)
    ]
    return router


def test_router_available_providers_honours_cooldown_and_fallback() -> None:
    router = _router("first", "second")
    assert router.available_providers() == ["first", "second"]
    router._cooldown_provider("first", seconds=300)
    assert router.available_providers() == ["second"]
    assert router.available_providers(allow_fallback=False) == []
    assert router.available_providers(provider="first") == []


def test_wrapper_uses_router_availability_before_dispatch() -> None:
    router = _router("first", "second")
    router._cooldown_provider("first", seconds=300)
    seen: list[str] = []

    def fake_call(
        provider: Any,
        model: str,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int | None,
    ) -> str:
        seen.append(provider.name)
        return "ok"

    router._call_openai_compatible = fake_call  # type: ignore[method-assign]

    blocked = asyncio.run(
        llm_wrapper.make_llm_call(router=router, max_retries=0)(
            {"user": "probe", "allow_fallback": False}
        )
    )
    assert blocked["text"] == ""
    assert "fail-closed" in blocked["error"]
    assert seen == []

    allowed = asyncio.run(
        llm_wrapper.make_llm_call(router=router, max_retries=0)({"user": "probe"})
    )
    assert allowed["text"] == "ok"
    assert seen == ["second"]


# ── 3. neutral provider timeout ─────────────────────────────────────────────


class _Provider:
    name = "custom_01"
    enabled = True
    api_key = "unit-test-key"
    base_url = "http://localhost:1"
    models = {"fast": "custom-fast"}


def test_agent_loop_uses_neutral_provider_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("openai")
    seen: dict[str, Any] = {}

    class _Completions:
        def create(self, **kwargs: Any) -> Any:
            seen.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))]
            )

    class _Client:
        chat = SimpleNamespace(completions=_Completions())

    def fake_client(**kwargs: Any) -> _Client:
        seen["client"] = kwargs
        return _Client()

    monkeypatch.setattr("openai.OpenAI", fake_client)
    loop = AgentLoop(
        llm=SimpleNamespace(providers=[_Provider()]),
        registry=build_default_registry(),
        verbose=False,
        provider_timeout_s=1.25,
    )
    out = loop._call_llm([{"role": "user", "content": "probe"}])
    assert out["ok"] is True
    assert seen["client"]["timeout"] == 1.25

    default_loop = AgentLoop(
        llm=SimpleNamespace(providers=[_Provider()]),
        registry=build_default_registry(),
        verbose=False,
    )
    assert default_loop._provider_timeout() == DEFAULT_TIMEOUT


# ── 4. bounded supervisor waits ─────────────────────────────────────────────


def test_parallel_executor_never_blocks_on_hung_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supervisor = supervisor_mod.Supervisor(use_rag=False, verbose=False, parallel_timeout_s=0.01)
    monkeypatch.setattr(
        supervisor.router,
        "decide",
        lambda prompt: RouteDecision(
            strategy="parallel",
            complexity="complex",
            category="code_generation",
            agents=["a", "b"],
            reason="",
        ),
    )

    class _Future:
        def done(self) -> bool:
            return False

        def cancel(self) -> bool:
            return True

    instances: list[Any] = []

    class _Executor:
        def __init__(self, max_workers: int) -> None:
            self.shutdown_kwargs: tuple[bool, bool] | None = None
            instances.append(self)

        def submit(self, fn: Any, *args: Any) -> _Future:
            return _Future()

        def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
            self.shutdown_kwargs = (wait, cancel_futures)

    def _never_completes(*args: Any, **kwargs: Any) -> Any:
        raise supervisor_mod.concurrent.futures.TimeoutError()

    monkeypatch.setattr(supervisor_mod.concurrent.futures, "ThreadPoolExecutor", _Executor)
    monkeypatch.setattr(supervisor_mod.concurrent.futures, "as_completed", _never_completes)

    out = supervisor.execute("probe")
    assert out["ok"] is False
    assert len(out["results"]) == 2
    assert all("timeout after" in result["error"] for result in out["results"])
    assert instances[0].shutdown_kwargs == (False, True)


# ── 5. mandatory LLM contract gate wiring ───────────────────────────────────


def test_llm_contract_gate_is_registered_and_wired() -> None:
    root = Path(__file__).resolve().parents[1]
    pytest_ini = (root / "pytest.ini").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert "llm_contract: mandatory LLM router/wrapper contract gate" in pytest_ini
    assert "python -m pytest -m llm_contract --tb=short" in workflow
