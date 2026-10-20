"""Tests for the jury-gate LLM adapter (``src.orchestrator.llm_adapter``).

The orchestrator hands ``llm`` to ``jury.judge``; the jury calls
``llm.generate(prompt, json_mode=True, temperature=0.0)`` and expects a RAW
STRING. The project router returns a dict and has no ``json_mode`` — these
tests pin the seam that makes the jury work with the real router.
"""
from __future__ import annotations

from typing import Any

from src.orchestrator.llm_adapter import RouterLLMAdapter, adapt_llm


class _DictRouter:
    """Mimics novamind ``LLMRouter.generate``: dict return, no ``json_mode``."""

    def __init__(self, text: str = '{"approved": true}', ok: bool = True) -> None:
        self.text = text
        self.ok = ok
        self.calls: list[dict[str, Any]] = []

    def generate(self, prompt: str, system: str = "", role: str = "fast",
                 temperature: float = 0.2, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"prompt": prompt, "system": system, "role": role,
                           "temperature": temperature})
        return {"ok": self.ok, "text": self.text, "provider": "fake",
                "elapsed": 0.0}


class _JsonModeRouter:
    """A provider-native router that DOES accept ``json_mode`` and returns str."""

    def generate(self, prompt: str, json_mode: bool = False,
                 **kwargs: Any) -> str:
        return '{"approved": false}' if json_mode else "plain"


class _BoomRouter:
    def generate(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("provider exploded")


# ── RouterLLMAdapter ────────────────────────────────────────────────────────

def test_adapter_returns_text_from_dict_router() -> None:
    r = _DictRouter('{"approved": true}')
    out = RouterLLMAdapter(r).generate("p", json_mode=True, temperature=0.0)
    assert out == '{"approved": true}'
    assert r.calls[0]["temperature"] == 0.0


def test_adapter_ignores_json_mode_when_router_lacks_it() -> None:
    """No TypeError leaks: the project router has no ``json_mode`` kwarg."""
    r = _DictRouter("x")
    assert RouterLLMAdapter(r).generate("p", json_mode=True) == "x"


def test_adapter_honours_native_json_mode_router() -> None:
    assert RouterLLMAdapter(_JsonModeRouter()).generate(
        "p", json_mode=True) == '{"approved": false}'


def test_adapter_returns_empty_on_failure() -> None:
    """Fail-closed: an exploding router yields "" (jury → parse_error)."""
    assert RouterLLMAdapter(_BoomRouter()).generate("p", json_mode=True) == ""


def test_adapter_returns_empty_on_not_ok() -> None:
    r = _DictRouter(text="ignored", ok=False)
    assert RouterLLMAdapter(r).generate("p") == ""


def test_adapter_returns_empty_without_router() -> None:
    assert RouterLLMAdapter(None).generate("p") == ""


def test_adapter_returns_empty_for_object_without_generate() -> None:
    assert RouterLLMAdapter(object()).generate("p") == ""


def test_adapter_str_result_passthrough() -> None:
    class _StrRouter:
        def generate(self, *a: Any, **k: Any) -> str:
            return "raw text"

    assert RouterLLMAdapter(_StrRouter()).generate("p") == "raw text"


def test_adapter_supports_alternate_text_keys() -> None:
    class _AltRouter:
        def generate(self, *a: Any, **k: Any) -> dict[str, Any]:
            return {"content": "from content key"}

    assert RouterLLMAdapter(_AltRouter()).generate("p") == "from content key"


def test_adapter_non_dict_non_str_result_is_stringified() -> None:
    class _WeirdRouter:
        def generate(self, *a: Any, **k: Any) -> int:
            return 42

    assert RouterLLMAdapter(_WeirdRouter()).generate("p") == "42"


def test_adapter_none_result_is_empty() -> None:
    class _NoneRouter:
        def generate(self, *a: Any, **k: Any) -> Any:
            return None

    assert RouterLLMAdapter(_NoneRouter()).generate("p") == ""


def test_adapter_falls_through_when_json_mode_raises_type_error() -> None:
    """A router that accepts ``**kwargs`` but TypeError-raises on ``json_mode``.

    First call (json_mode=True) raises TypeError → the adapter retries without
    the kwarg and returns the honest result.
    """
    class _PickyRouter:
        def generate(self, prompt: str, json_mode: bool = False,
                     **kwargs: Any) -> str:
            if json_mode:
                raise TypeError("unexpected keyword argument 'json_mode'")
            return "second try"

    assert RouterLLMAdapter(_PickyRouter()).generate(
        "p", json_mode=True) == "second try"


# ── adapt_llm (preserve a contract-correct object, wrap the rest) ───────────

def test_adapt_llm_keeps_contract_correct_double() -> None:
    class _Double:
        def generate(self, p: str, json_mode: bool = True,
                     temperature: float = 0.0) -> str:
            return '{"approved": true}'

    d = _Double()
    assert adapt_llm(d) is d


def test_adapt_llm_wraps_dict_router() -> None:
    wrapped = adapt_llm(_DictRouter())
    assert isinstance(wrapped, RouterLLMAdapter)


def test_adapt_llm_wraps_router_that_rejects_json_mode_probe() -> None:
    """A positional-only router: the ``json_mode`` probe raises TypeError → wrap."""
    class _NoKwargsRouter:
        def __init__(self) -> None:
            self.seen: list[str] = []

        def generate(self, prompt: str, /, **kwargs: Any) -> str:
            if "json_mode" in kwargs:
                raise TypeError("no json_mode")
            return "ok"

    assert isinstance(adapt_llm(_NoKwargsRouter()), RouterLLMAdapter)


def test_adapt_llm_wraps_object_without_generate() -> None:
    assert isinstance(adapt_llm(object()), RouterLLMAdapter)


def test_adapt_llm_none_stays_none() -> None:
    assert adapt_llm(None) is None


def test_adapt_llm_keeps_generate_that_raises_on_probe() -> None:
    """A contract-shaped object that merely raised on the empty probe is kept."""
    class _RaisesOnProbe:
        def generate(self, prompt: str, json_mode: bool = False,
                     temperature: float = 0.2) -> str:
            if prompt == "":
                raise ValueError("empty prompt")
            return "ok"

    obj = _RaisesOnProbe()
    assert adapt_llm(obj) is obj


def test_adapted_router_feeds_the_jury() -> None:
    """End-to-end: the adapter makes a real HIGH-risk jury verdict possible."""
    from src.novamind.council.jury import judge
    from src.orchestrator.risk import RiskLevel

    llm = RouterLLMAdapter(_DictRouter('{"approved": true, "confidence": 0.9}'))
    v = judge("some context", risk=RiskLevel.HIGH, members=["a", "b"], llm=llm)
    assert v is not None
    assert v.approved is True
    assert v.members_approved == 2
