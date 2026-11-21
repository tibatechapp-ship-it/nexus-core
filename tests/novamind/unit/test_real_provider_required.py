import asyncio

from novamind.core.llm_router import ProviderConfig
from novamind.factory import llm_wrapper


class RealContractRouter:
    def __init__(self):
        self.providers = [
            ProviderConfig(
                name="integration-test-provider",
                api_key="test-key",
                base_url="https://provider.invalid/v1",
                models={"fast": "test-model", "smart": "test-model"},
            )
        ]

    def generate(
        self, prompt, system="", role="fast", temperature=0.2,
        max_tokens=None, provider=None, allow_fallback=True,
    ):
        return {
            "ok": True,
            "text": "real-provider-contract-response",
            "provider": "integration-test-provider",
            "model": "test-model",
            "elapsed": 0.01,
        }


def test_factory_wrapper_fails_closed_without_provider(monkeypatch):
    monkeypatch.setattr(llm_wrapper, "_load_router", lambda: None)

    assert llm_wrapper.is_llm_available() is False
    result = asyncio.run(llm_wrapper.make_llm_call()({"user": "run task"}))

    assert result["ok"] is False
    assert result["simulated"] is False
    assert result["provider"] == "none"
    assert result["text"] == ""
    assert result["error"] == "no real LLM provider configured"


def test_factory_wrapper_marks_explicit_mock_fallback(monkeypatch):
    monkeypatch.setattr(llm_wrapper, "_load_router", lambda: None)

    result = asyncio.run(
        llm_wrapper.make_llm_call(fallback_to_mock=True)({"user": "test task"})
    )

    assert result["ok"] is True
    assert result["simulated"] is True
    assert result["provider"] == "mock"


def test_factory_wrapper_uses_router_adapter_for_real_provider(monkeypatch):
    router = RealContractRouter()
    monkeypatch.setattr(llm_wrapper, "_load_router", lambda: router)

    result = asyncio.run(
        llm_wrapper.make_llm_call(max_retries=0)({
            "system": "Be precise",
            "user": "Return a short response",
        })
    )

    assert result["ok"] is True
    assert result["simulated"] is False
    assert result["provider"] == "integration-test-provider"
    assert result["text"] == "real-provider-contract-response"


def test_factory_wrapper_does_not_fallback_after_real_provider_failure(monkeypatch):
    class FailingRouter(RealContractRouter):
        def generate(self, *args, **kwargs):
            return {
                "ok": False,
                "text": "",
                "provider": "integration-test-provider",
                "error": "upstream rejected request",
            }

    monkeypatch.setattr(llm_wrapper, "_load_router", lambda: FailingRouter())
    result = asyncio.run(
        llm_wrapper.make_llm_call(max_retries=0)({"user": "must not be mocked"})
    )

    assert result["ok"] is False
    assert result["simulated"] is False
    assert result["text"] == ""
    assert "upstream rejected request" in result["error"]


def test_factory_wrapper_rejects_generic_router_identity(monkeypatch):
    class UnidentifiedRouter(RealContractRouter):
        def generate(self, prompt, system="", role="fast", **kwargs):
            return {
                "ok": True,
                "text": "response without source identity",
                "model": "test-model",
            }

    monkeypatch.setattr(llm_wrapper, "_load_router", lambda: UnidentifiedRouter())
    result = asyncio.run(
        llm_wrapper.make_llm_call(max_retries=0)({"user": "must identify source"})
    )

    assert result["ok"] is False
    assert result["simulated"] is False
    assert result["text"] == ""
    assert "provider" in result["error"].lower()
