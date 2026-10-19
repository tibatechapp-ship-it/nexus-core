"""Tests for monitoring."""
import os
import sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from src.nexus.monitoring import Monitor


@pytest.fixture
def mon(tmp_path):
    return Monitor(log_dir=str(tmp_path / "metrics"))


def test_empty_stats(mon):
    stats = mon.get_today_stats()
    assert stats["total_calls"] == 0
    assert stats["success_rate"] == 0.0


def test_log_successful_call(mon):
    mon.log_call(
        provider="groq_01",
        model="qwen",
        elapsed=1.5,
        ok=True,
        prompt="test prompt",
        response="test response",
    )
    stats = mon.get_session_stats()
    assert stats["total_calls"] == 1
    assert stats["successes"] == 1
    assert stats["failures"] == 0
    assert stats["success_rate"] == 100.0


def test_log_failed_call(mon):
    mon.log_call(
        provider="groq_01",
        model="qwen",
        elapsed=0.5,
        ok=False,
        error="test error",
    )
    stats = mon.get_session_stats()
    assert stats["failures"] == 1
    assert stats["success_rate"] == 0.0


def test_token_estimation(mon):
    mon.log_call(
        provider="groq",
        model="qwen",
        elapsed=1.0,
        ok=True,
        prompt="a" * 100,  # ~25 tokens
        response="b" * 40,  # ~10 tokens
    )
    stats = mon.get_session_stats()
    assert stats["total_tokens_in"] >= 20
    assert stats["total_tokens_out"] >= 8


def test_cost_calculation(mon):
    mon.log_call(
        provider="groq",
        model="qwen",
        elapsed=1.0,
        ok=True,
        prompt="x" * 4000,  # ~1000 tokens
        response="y" * 4000,  # ~1000 tokens
    )
    stats = mon.get_session_stats()
    # 1000 in @ $0.05/1M + 1000 out @ $0.08/1M = ~$0.00013
    assert stats["total_cost_usd"] > 0
    assert stats["total_cost_usd"] < 0.001


def test_by_provider_stats(mon):
    mon.log_call(provider="groq_01", model="qwen", elapsed=1.0, ok=True, prompt="a", response="b")
    mon.log_call(provider="groq_02", model="qwen", elapsed=1.0, ok=True, prompt="a", response="b")
    mon.log_call(provider="gemini_1", model="gemini", elapsed=1.0, ok=True, prompt="a", response="b")

    stats = mon.get_session_stats()
    assert len(stats["by_provider"]) == 3
    assert stats["by_provider"]["groq_01"]["calls"] == 1


def test_clear(mon):
    mon.log_call(provider="groq", model="qwen", elapsed=1.0, ok=True, prompt="a", response="b")
    count = mon.clear_today()
    assert count == 1
    assert mon.get_today_stats()["total_calls"] == 0


# ── self-healing: إعادة التسلّح بعد استبدال الصنف (فخّ importlib.reload) ──

def _fake_router_module():
    """وحدة llm_router مزيفة بصنف جديد غير مُلفّف (محاكاة reload)."""
    import types

    class FakeRouter:
        def generate(self, prompt="", system="", provider=None, **kwargs):
            return {"ok": True, "provider": "groq_01", "model": "qwen", "text": "x"}

    mod = types.ModuleType("novamind.core.llm_router")
    mod.LLMRouter = FakeRouter
    return mod, FakeRouter


def test_patch_re_wraps_a_fresh_class_even_when_the_flag_lies(monkeypatch):
    """علم _patched قديم True لكن الصنف الحالي خام → يجب أن نلفّه بالفحص.

    هذا هو السيناريو الفعلي: تقرير ``importlib.reload(llm_router)`` يُنشئ
    صنفًا جديدًا بينما يبقى ``_patched`` على True فيعود patch_llm_router()
    مبكرًا ويفشل اللفّ صامتًا.
    """
    from src.nexus import monitoring_patch

    mod, FakeRouter = _fake_router_module()
    monkeypatch.setitem(sys.modules, "novamind.core.llm_router", mod)
    monkeypatch.setattr(monitoring_patch, "_patched", True)  # علم قديم كاذب

    assert getattr(FakeRouter.generate, monitoring_patch._MARKER, False) is False

    assert monitoring_patch.patch_llm_router() is True

    assert getattr(FakeRouter.generate, monitoring_patch._MARKER, False) is True
    assert getattr(FakeRouter.generate, "__wrapped__", None) is not None


def test_patch_is_idempotent_on_the_same_class(monkeypatch):
    """نداء ثانٍ على نفس الصنف لا يلفّ مرّتين (الغلاف لا يلفّ نفسه)."""
    from src.nexus import monitoring_patch

    mod, FakeRouter = _fake_router_module()
    monkeypatch.setitem(sys.modules, "novamind.core.llm_router", mod)
    monkeypatch.setattr(monitoring_patch, "_patched", False)

    assert monitoring_patch.patch_llm_router() is True
    first_wrapper = FakeRouter.generate

    assert monitoring_patch.patch_llm_router() is True
    assert FakeRouter.generate is first_wrapper


def test_patch_fails_gracefully_without_the_router(monkeypatch):
    """لو غاب llm_router نُرجع False بلا استثناء (تدهور آمن)."""
    from src.nexus import monitoring_patch

    monkeypatch.setitem(sys.modules, "novamind.core.llm_router", None)

    assert monitoring_patch.patch_llm_router() is False
