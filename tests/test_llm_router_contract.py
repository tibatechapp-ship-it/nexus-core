"""اختبار عقد المزوّد — llm_router stable interface (docs/V2_ROADMAP.md م3 — ض7).

العقد: أي تغيير في توقيع الدوال العامة أو سلوك قاطع الدارة (circuit
breaker) يُفشل هذا الاختبار — التعديل يستوجب مراجعة معلنة وتحديث
``docs/CONTRACTS.md`` في PR نفسه.
"""

from __future__ import annotations

import importlib
import inspect
import sys
import time
from pathlib import Path
from typing import Any

import pytest

# الوحدة تعيش تحت src/ — نفس أسلوب tests/novamind/conftest.py.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from novamind.core import llm_router as lr  # noqa: E402
from novamind.core.llm_router import (  # noqa: E402
    LLMRouter,
    MockProvider,
    ProviderConfig,
    get_router,
)

# ═══ 1. التوقيعات المثبتة — docs/CONTRACTS.md §1.1 ══════════════════════════════

EXPECTED_SIGNATURES: dict[str, str] = {
    "generate": (
        "(self, prompt, system='', role='fast', temperature=0.2, "
        "max_tokens=None, provider=None, allow_fallback=True)"
    ),
    "generate_for_task": (
        "(self, task_type: str, prompt: str, system: str = '', "
        "temperature: float = 0.2, max_tokens=None) -> Dict"
    ),
    "async_generate": (
        "(self, prompt: str, system: str = '', role: str = 'fast', "
        "temperature: float = 0.2, max_tokens: int = 2000) -> Dict"
    ),
    "async_generate_for_task": (
        "(self, task_type: str, prompt: str, system: str = '', "
        "temperature: float = 0.2, max_tokens: int = 2000) -> Dict"
    ),
    "async_generate_batch": "(self, requests: List[Dict]) -> List[Dict]",
    "list_providers": "(self)",
    "stats": "(self)",
    "_cooldown_provider": "(self, name: str, seconds: int = 300) -> None",
    "_is_cooled_down": "(self, name: str) -> bool",
    "_classify_cooldown": "(self, status, err, headers)",
    "_parse_duration": "(self, s)",
    "_key_hash": "(self, key)",
    "_extract_status": "(self, exc)",
}


@pytest.mark.parametrize("name", sorted(EXPECTED_SIGNATURES))
def test_signature_unchanged(name: str) -> None:
    sig = str(inspect.signature(getattr(LLMRouter, name)))
    assert sig == EXPECTED_SIGNATURES[name], (
        f"عقد llm_router انكسر على '{name}':\n  المتوقع: {EXPECTED_SIGNATURES[name]}"
        f"\n  الفعلي:  {sig}\nحدّث docs/CONTRACTS.md ومرّر التغيير بمراجعة معلنة."
    )


def test_get_router_signature_unchanged() -> None:
    assert "LLMRouter" in str(inspect.signature(get_router))


def test_mock_provider_signature_unchanged() -> None:
    assert str(inspect.signature(MockProvider.generate)) == \
        "(self, prompt, system='', **kwargs)"


def test_provider_config_fields_unchanged() -> None:
    cfg = ProviderConfig(name="n", api_key="k", base_url="u", models={"fast": "m"})
    assert cfg.priority == 100 and cfg.enabled is True
    assert cfg.calls == 0 and cfg.failures == 0
    assert cfg.last_error == "" and cfg.last_call_at == 0.0


# ═══ 2. عقد النتيجة — docs/CONTRACTS.md §1.2 ════════════════════════════════════


def test_result_success_shape() -> None:
    result = MockProvider().generate("hello")
    assert result["ok"] is True
    for key in ("text", "provider", "model", "elapsed"):
        assert key in result


def test_result_unknown_provider_is_failure_dict_not_exception() -> None:
    router = LLMRouter()
    result = router.generate("p", provider="__no_such_provider__")
    assert result["ok"] is False
    assert "error" in result


# ═══ 3. عقد قاطع الدارة — docs/CONTRACTS.md §1.3 ════════════════════════════════


@pytest.fixture()
def router() -> LLMRouter:
    return LLMRouter()


def test_circuit_breaker_constants_unchanged() -> None:
    assert LLMRouter._COOLDOWN_DAILY == 86400
    assert LLMRouter._COOLDOWN_HOURLY == 3600
    assert LLMRouter._COOLDOWN_MINUTE == 60
    assert LLMRouter._COOLDOWN_BRIEF == 30


def test_cooldown_blocks_and_expires(router: LLMRouter) -> None:
    router._cooldown_provider("prov-a", seconds=300)
    assert router._is_cooled_down("prov-a") is False  # مبرَد الآن
    router._cooldowns["prov-a"] = time.time() - 1     # انقضى
    assert router._is_cooled_down("prov-a") is True


def test_classify_401_invalid_key(router: LLMRouter) -> None:
    secs, reason = router._classify_cooldown(401, "", {})
    assert (secs, reason) == (86400, "invalid_key")


def test_classify_404_model_retired(router: LLMRouter) -> None:
    secs, reason = router._classify_cooldown(404, "model no longer available", {})
    assert (secs, reason) == (86400, "model_retired")


def test_classify_429_plain_is_one_minute(router: LLMRouter) -> None:
    secs, reason = router._classify_cooldown(429, "too many requests", {})
    assert (secs, reason) == (60, "rate_limit")


def test_classify_429_daily_quota(router: LLMRouter) -> None:
    secs, reason = router._classify_cooldown(429, "quota exceeded for today", {})
    assert (secs, reason) == (86400, "daily_quota")


def test_classify_429_retry_after_header(router: LLMRouter) -> None:
    secs, reason = router._classify_cooldown(
        429, "", {"retry-after": "120"})
    assert secs >= 120 and reason == "rate_limit_reset"


def test_classify_5xx_is_120s(router: LLMRouter) -> None:
    secs, reason = router._classify_cooldown(503, "", {})
    assert (secs, reason) == (120, "server_error")


def test_classify_timeout_is_brief(router: LLMRouter) -> None:
    secs, reason = router._classify_cooldown(None, "connection timed out", {})
    assert (secs, reason) == (30, "network")


def test_classify_unknown_defaults_to_minute(router: LLMRouter) -> None:
    secs, reason = router._classify_cooldown(None, "weird", {})
    assert (secs, reason) == (60, "unknown")


@pytest.mark.parametrize(("raw", "expected"), [
    ("120", 120), ("90s", 90), ("5m", 300), ("2h", 7200),
    ("1h30m", 5400), ("", None),
])
def test_parse_duration_contract(router: LLMRouter, raw: str,
                                 expected: int | None) -> None:
    assert router._parse_duration(raw) == expected


def test_key_hash_is_12_hex(router: LLMRouter) -> None:
    h = router._key_hash("secret-key")
    assert len(h) == 12 and all(c in "0123456789abcdef" for c in h)


def test_extract_status_from_attribute_and_response_and_text(
    router: LLMRouter,
) -> None:
    class E1(Exception):
        status_code = 429

    assert router._extract_status(E1()) == 429

    class Resp:
        status_code = 503

    class E2(Exception):
        response = Resp()

    assert router._extract_status(E2()) == 503
    assert router._extract_status(Exception("HTTP 418 exploded")) == 418
    assert router._extract_status(Exception("nothing")) is None


def test_cooled_provider_skipped_in_generate_loop(
    router: LLMRouter, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """العقد السلوكي: مزوّد مبرَد يُتخطّى داخل حلقة generate، والحلقة
    تسقط إلى أول غير مبرَد — لا استثناء ولا انسداد."""
    monkeypatch.setattr(
        LLMRouter, "_cooldown_path",
        lambda self: tmp_path / "cooldowns.json", raising=True,
    )
    monkeypatch.setattr(
        router, "_call_openai_compatible",
        lambda p, model, prompt, system, temperature, max_tokens: "ok-text",
        raising=True,
    )
    monkeypatch.setattr(
        router, "_call_gemini",
        lambda p, model, prompt, system, temperature, max_tokens: "ok-text",
        raising=True,
    )
    names = [p.name for p in router.providers]
    assert names, "لا مزودين محمّلين — بيئة الاختبار مكسورة"
    survivor = names[-1]
    for n in names[:-1]:
        router._cooldowns[n] = time.time() + 999
    result = router.generate("probe")
    assert result["ok"] is True
    assert result["provider"] == survivor


def test_stats_and_list_providers_shape(router: LLMRouter) -> None:
    st = router.stats()
    for key in ("total_providers", "total_calls", "total_failures", "providers"):
        assert key in st
    for p in router.list_providers():
        for key in ("name", "priority", "enabled", "calls", "failures",
                    "models", "last_error"):
            assert key in p


def test_get_router_returns_llm_router() -> None:
    assert isinstance(get_router(), LLMRouter)


def test_module_reloads_cleanly() -> None:
    """إعادة تحميل الوحدة لا تفشل — أساس استقرار الاختبارات الأخرى."""
    fresh = importlib.reload(lr)
    assert hasattr(fresh, "LLMRouter") and hasattr(fresh, "get_router")
