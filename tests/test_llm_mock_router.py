from __future__ import annotations

import pytest

from novamind.core.llm_router import LLMRouter
from src.llm.mock_router import setup_mock


def _restore_router_class(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "generate",
        "generate_for_task",
        "_load_from_env",
        "_cooldown_provider",
        "_is_cooled_down",
    ):
        if hasattr(LLMRouter, name):
            monkeypatch.setattr(LLMRouter, name, getattr(LLMRouter, name))
        else:
            monkeypatch.setattr(LLMRouter, name, None, raising=False)


def test_setup_mock_installs_explicit_deterministic_simulation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _restore_router_class(monkeypatch)
    setup_mock()
    router = LLMRouter()
    assert router.providers == []

    result = router.generate("short prompt", system="generic")
    assert result == {
        "ok": True,
        "text": "[Mock] short prompt",
        "provider": "mock",
        "model": "mock",
        "elapsed": 0.01,
        "simulated": True,
    }
    assert router.generate("x" * 100)["text"] == "[Mock] " + "x" * 80


@pytest.mark.parametrize(
    ("system", "prompt", "expected"),
    [
        ("أنت الناقد", "راجع الحجتين", "بعد المراجعة: متسقتان. مقبول."),
        ("أنت الناقد", "حلل المهمة", "أراجع الحجتين. مقبول."),
        ("أنت المحلل المتشكك", "راجع الحجتين", "خطر: نقص السياق الأمني."),
        ("أنت المحلل المتشكك", "حلل المهمة", "خطر: 3 مخاوف أمنية."),
        ("أنت المحلل المدافع", "راجع الحجتين", "آمن: يمكن التخفيف."),
        ("أنت المحلل المدافع", "حلل المهمة", "آمن: الطلب مقبول."),
    ],
)
def test_mock_role_responses_are_predictable(
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    prompt: str,
    expected: str,
) -> None:
    _restore_router_class(monkeypatch)
    monkeypatch.setattr(LLMRouter, "_load_from_env", lambda self: setattr(self, "providers", []))
    setup_mock()
    result = LLMRouter().generate(prompt, system=system)
    assert result["text"] == expected
    assert result["simulated"] is True
    assert result["model"] == "mock"


def test_mock_router_compatibility_methods_are_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _restore_router_class(monkeypatch)
    monkeypatch.setattr(LLMRouter, "_load_from_env", lambda self: setattr(self, "providers", []))
    setup_mock()
    router = LLMRouter()
    result = router.generate_for_task("review", "prompt", system="generic")
    assert result["simulated"] is True
    assert result["text"] == "[Mock] prompt"
    assert result["model"] == "mock"
    router._cooldown_provider("mock", seconds=5)
    assert router._is_cooled_down("mock") is True
