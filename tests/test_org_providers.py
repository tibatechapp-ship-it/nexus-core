"""اختبارات مزوّدي النماذج — حتمية، بدائل، استهلاك، مُكيّف حقيقي.

القواعد المفروضة: نفس المطالبة نفس الرد (بلا شبكة)، فشل سلسلة النماذج
يُرفع بعد استنفادها، الكلفة صفر لغير المدرج، ولا مفتاح في أي رسالة خطأ.
"""

from __future__ import annotations

import pytest

from src.org.providers import (
    ModelResponse,
    OpenAICompatProvider,
    PRICE_TABLE,
    ProviderConfig,
    ProviderError,
    ProviderPool,
    Usage,
    estimate_cost,
)


def _mk_pool(models: list[str]) -> ProviderPool:
    return ProviderPool([ProviderConfig(name="mock", model=m)
                         for m in models])


class TestMockDeterminism:
    def test_same_prompt_same_reply(self) -> None:
        pool = _mk_pool(["mock-1"])
        msgs = [{"role": "system", "content": "[AGENT:dev:backend]"},
                {"role": "user", "content": "TASK: x\nFUNCTION: divide\n"
                                            "TARGET FILES:\nfile: a.py"}]
        r1 = pool.get().complete(msgs)
        r2 = pool.get().complete(msgs)
        assert r1.text == r2.text

    def test_role_dispatch_dev(self) -> None:
        pool = _mk_pool(["mock-1"])
        out = pool.get().complete([
            {"role": "system", "content": "[AGENT:dev:backend]"},
            {"role": "user", "content": "FUNCTION: divide\n"
                                        "GUARD: صفر\nTARGET FILES:\n"
                                        "file: calc/mathops.py\n"
                                        "file: tests/test_mathops.py"}])
        assert '"changed_files"' in out.text
        assert "calc/mathops.py" in out.text

    def test_role_dispatch_review_lens(self) -> None:
        pool = _mk_pool(["mock-1"])
        out = pool.get().complete([
            {"role": "system", "content": "[AGENT:review:logic]"},
            {"role": "user", "content": "راجع\nDIFF:\n- print('x')\n"}])
        assert '"verdict"' in out.text

    def test_diff_scan_flags_bare_except(self) -> None:
        """فحص المراجعة الحقيقي: استثناء عارٍ في الرقعة يُكتشف."""
        pool = _mk_pool(["mock-1"])
        out = pool.get().complete([
            {"role": "system", "content": "[AGENT:review:logic]"},
            {"role": "user", "content": "راجع\nDIFF:\n- except:\n-  pass\n"}])
        assert '"request_changes"' in out.text

    def test_diff_scan_flags_eval(self) -> None:
        pool = _mk_pool(["mock-1"])
        out = pool.get().complete([
            {"role": "system", "content": "[AGENT:review:security]"},
            {"role": "user", "content": "راجع\nDIFF:\n- eval(user_input)\n"}])
        assert '"request_changes"' in out.text

    def test_unknown_tag_generic(self) -> None:
        pool = _mk_pool(["mock-1"])
        out = pool.get().complete([
            {"role": "user", "content": "بلا وسم"}])
        assert '"note"' in out.text


class TestFallbackAndCost:
    def test_cost_zero_for_unlisted(self) -> None:
        usage = Usage(in_tokens=1000, out_tokens=500)
        assert estimate_cost("unknown-model", usage) == 0.0

    def test_cost_listed_model(self) -> None:
        usage = Usage(in_tokens=1_000_000, out_tokens=0)
        assert estimate_cost("gpt-4o", usage) == 2.50

    def test_price_table_mock_free(self) -> None:
        assert PRICE_TABLE["mock-1"] == (0.0, 0.0)

    def test_fallback_chain_records_errors(self) -> None:
        """فشل كل السلسلة يرفع بخلاصة الأخطاء مسجلة."""
        pool = _mk_pool(["mock-1"])

        class Boom:
            def complete(self, *a: object, **k: object) -> ModelResponse:
                raise ProviderError("انفجار مزوّد")

        pool.get = lambda name="", model="": Boom()  # type: ignore[assignment]
        with pytest.raises(ProviderError, match="استُنفدت"):
            pool.complete_with_fallback([{"role": "user", "content": "x"}])
        assert pool.last_errors


class TestRealAdapterGuards:
    def test_missing_base_url_rejected(self) -> None:
        with pytest.raises(ProviderError, match="base_url"):
            OpenAICompatProvider(ProviderConfig(name="openai-compat",
                                                model="m", base_url=""))

    def test_error_message_has_no_key(self) -> None:
        """رسالة الفشل لا تحمل مفتاحًا ولا رأس تفويض."""
        provider = OpenAICompatProvider(ProviderConfig(
            name="openai-compat", model="m",
            base_url="http://127.0.0.1:9/v1", api_key="super-secret-key"))
        with pytest.raises(ProviderError) as exc_info:
            provider.complete([{"role": "user", "content": "hi"}])
        assert "super-secret-key" not in str(exc_info.value)


class TestPoolFromEnv:
    def test_mock_only_without_env(self) -> None:
        from src.org.providers import pool_from_env_vars
        p = pool_from_env_vars({})
        assert p.models() == ["mock-1"]

    def test_real_first_mock_fallback(self) -> None:
        from src.org.providers import pool_from_env_vars
        p = pool_from_env_vars({"ORG_LLM_BASE_URL": "http://x/v1",
                                "ORG_LLM_MODEL": "llama-3"})
        assert p.models() == ["llama-3", "mock-1"]
