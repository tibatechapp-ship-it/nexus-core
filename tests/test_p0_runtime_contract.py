"""Regression tests for the P0 runtime + default read-only contract."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import src.memory.agent_rag_bridge as rag_mod
from novamind.core.llm_router import LLMRouter, ProviderConfig
from novamind.factory import llm_wrapper
from src.agent_loop.tools import build_default_registry

pytestmark = pytest.mark.llm_contract


def _router_with_provider(name: str = "contract") -> LLMRouter:
    router = LLMRouter()
    router.providers = [
        ProviderConfig(
            name=name,
            api_key="unit-test-key",
            base_url="",
            models={"fast": "contract-fast", "smart": "contract-smart"},
        )
    ]
    return router


def test_llm_wrapper_uses_canonical_router_generate_contract() -> None:
    """The wrapper must call LLMRouter.generate with its real keyword names."""
    router = _router_with_provider()
    seen: dict[str, object] = {}

    def fake_call(provider, model, prompt, system, temperature, max_tokens):
        seen.update(
            provider=provider.name,
            model=model,
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return "رد حقيقي من المسار المتوافق"

    router._call_openai_compatible = fake_call  # type: ignore[method-assign]
    call = llm_wrapper.make_llm_call(router=router)
    out = asyncio.run(
        call(
            {
                "user": "سؤال",
                "system": "تعليمات",
                "role": "smart",
                "temperature": 0.3,
                "max_tokens": 123,
            }
        )
    )

    assert out["text"] == "رد حقيقي من المسار المتوافق"
    assert out["provider"] == "contract"
    assert seen["provider"] == "contract"
    assert seen["model"] == "contract-smart"
    assert seen["prompt"] == "سؤال"
    assert seen["system"] == "تعليمات"
    assert seen["temperature"] == pytest.approx(0.3)
    assert seen["max_tokens"] == 123


def test_llm_wrapper_fails_closed_without_enabled_provider() -> None:
    router = LLMRouter()
    router.providers = []
    out = asyncio.run(llm_wrapper.make_llm_call(router=router)({"user": "سؤال"}))
    assert out["text"] == ""
    assert out["provider"] == "none"
    assert "fail-closed" in out["error"]
    assert "[MOCK]" not in out["text"]


def test_llm_wrapper_fails_closed_on_empty_provider_text() -> None:
    router = _router_with_provider()
    router._call_openai_compatible = lambda *a, **k: ""  # type: ignore[method-assign]
    out = asyncio.run(llm_wrapper.make_llm_call(router=router, max_retries=0)({"user": "سؤال"}))
    assert out["text"] == ""
    assert "empty response" in out["error"] or "استجابة فارغة" in out["error"]


def test_is_llm_available_checks_enabled_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    router = LLMRouter()
    router.providers = [
        ProviderConfig(
            name="disabled",
            api_key="unit-test-key",
            base_url="",
            models={"fast": "off"},
            enabled=False,
        )
    ]
    monkeypatch.setitem(llm_wrapper._router_cache, "router", router)
    assert llm_wrapper.is_llm_available() is False

    router.providers = [
        ProviderConfig(
            name="enabled",
            api_key="unit-test-key",
            base_url="",
            models={"fast": "on"},
        )
    ]
    assert llm_wrapper.is_llm_available() is True


def test_default_registry_never_exposes_memory_write(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUS_ENABLE_MEMORY_WRITES", raising=False)
    reg = build_default_registry()
    assert "remember" not in reg.tools
    assert "غير موجودة" in reg.call("remember", {"text": "سر", "approval": "yes"})


def test_memory_write_requires_opt_in_and_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUS_ENABLE_MEMORY_WRITES", raising=False)
    assert "remember" not in build_default_registry(include_memory_write=True).tools

    saved: list[str] = []

    def fake_remember(text: str) -> str:
        saved.append(text)
        return "d-1"

    monkeypatch.setenv("NEXUS_ENABLE_MEMORY_WRITES", "1")
    monkeypatch.setattr(
        rag_mod,
        "get_bridge",
        lambda: SimpleNamespace(remember=fake_remember),
    )
    reg = build_default_registry(include_memory_write=True)

    assert "موافقة" in reg.call("remember", {"text": "ملاحظة"})
    assert saved == []
    assert reg.call("remember", {"text": "ملاحظة", "approval": True}) == "تم الحفظ: d-1"
    assert saved == ["ملاحظة"]
