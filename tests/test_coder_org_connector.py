"""Contract tests for the organization-to-coder connector adapter."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.coder.org_connector import OrgRuntimeConnector
from src.org.providers import ProviderError


class FakePool:
    def models(self) -> list[str]:
        return ["primary-model", "fallback-model"]


class FakeRuntime:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.pool = FakePool()
        self.fail = fail
        self.calls: list[tuple[object, str]] = []

    def complete(self, spec: object, prompt: str) -> object:
        self.calls.append((spec, prompt))
        if self.fail is not None:
            raise self.fail
        return SimpleNamespace(
            text='{"goal":"safe change"}',
            usage=SimpleNamespace(in_tokens=11, out_tokens=7, cost_usd=0.002),
            provider="mock",
            model="mock-1",
        )


def test_adapter_preserves_raw_response_and_usage() -> None:
    runtime = FakeRuntime()
    connector = OrgRuntimeConnector(runtime, mission_id="mission-1")

    result = asyncio.run(connector.generate("ordinary coder request"))

    assert result["ok"] is True
    assert result["reply"] == '{"goal":"safe change"}'
    assert result["usage"] == {
        "tokens_in": 11, "tokens_out": 7, "cost_usd": 0.002
    }
    spec, prompt = runtime.calls[0]
    assert prompt == "ordinary coder request"
    assert spec.role == "coder:worker"
    assert spec.dept == "development"
    assert spec.mission_id == "mission-1"
    assert spec.models == ["primary-model", "fallback-model"]


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("You are the planning stage.", "coder:planner"),
        ("You are the defect-discovery stage.", "coder:detector"),
    ],
)
def test_adapter_assigns_declared_stage_roles(prompt: str, expected: str) -> None:
    runtime = FakeRuntime()
    connector = OrgRuntimeConnector(runtime, mission_id="mission-2")

    result = asyncio.run(connector.generate(prompt))

    assert result["ok"] is True
    assert runtime.calls[0][0].role == expected


def test_adapter_contains_provider_failure() -> None:
    runtime = FakeRuntime(fail=ProviderError("provider unavailable"))
    connector = OrgRuntimeConnector(runtime, mission_id="mission-3")

    result = asyncio.run(connector.generate("request"))

    assert result["ok"] is False
    assert "ProviderError" in result["error"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mission_id": ""},
        {"mission_id": "m", "max_tokens": 0},
        {"mission_id": "m", "max_retries": -1},
        {"mission_id": "m", "timeout_s": 0},
    ],
)
def test_adapter_rejects_invalid_contract(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        OrgRuntimeConnector(FakeRuntime(), **kwargs)


def test_adapter_rejects_empty_prompt_without_provider_call() -> None:
    runtime = FakeRuntime()
    connector = OrgRuntimeConnector(runtime, mission_id="mission-4")

    result = asyncio.run(connector.generate("  "))

    assert result == {"ok": False, "error": "prompt must not be empty"}
    assert runtime.calls == []
