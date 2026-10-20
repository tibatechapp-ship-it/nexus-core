"""LLM adapter — bridge a project router to the jury gate's contract.

``src/orchestrator/orchestrator.py`` hands ``self.llm`` to
``src.novamind.council.jury.judge``, and ``jury._invoke_member`` calls::

    raw = llm.generate(prompt, json_mode=True, temperature=0.0)

It expects a **raw string** (the JSON blob it then ``re.search`` es).

The project's real router (``novamind.core.llm_router.LLMRouter``) has a
different signature — no ``json_mode`` kwarg — and returns a **dict**
``{"ok", "text", "provider", ...}``. Passing it straight in makes every
HIGH-risk verdict fail closed with a ``TypeError`` (``unexpected keyword
argument 'json_mode'``), so the gate silently rejects every high-risk action.

This adapter is that missing seam: it accepts the jury's call shape, forwards
the prompt to the router, and returns ``res["text"]`` (or ``""`` on failure) —
exactly the string the jury parses. It never raises: a broken/failed router
degrades to an empty string, which the jury already treats as ``parse_error``
(fail-closed), matching the gate's own hardening.

Duck-typed on purpose: any object exposing ``generate(prompt, system=, role=,
temperature=, ...)`` works. ``json_mode`` is accepted and ignored when the
underlying router does not support it. A router that DOES accept ``json_mode``
(e.g. a provider-native client) is honoured with a single retry.
"""
from __future__ import annotations

from typing import Any


class RouterLLMAdapter:
    """Wrap a project router so ``jury.judge(llm=...)`` can consume it."""

    def __init__(self, router: Any, *, role: str = "fast",
                 system: str = "") -> None:
        self.router = router
        self.role = role
        self.system = system

    def generate(self, prompt: str, *, json_mode: bool = False,
                 temperature: float = 0.2, **kwargs: Any) -> str:
        """Return the router's answer as a raw string (jury contract).

        Tries ``json_mode`` first (native routers); on ``TypeError`` — the
        project router has no such kwarg — retries without it. Returns ``""``
        on any error so the jury fails closed instead of crashing.
        """
        if self.router is None or not hasattr(self.router, "generate"):
            return ""
        call = dict(kwargs)
        call.setdefault("system", self.system)
        call.setdefault("role", self.role)
        call["temperature"] = temperature
        try:
            if json_mode:
                try:
                    return _as_text(self.router.generate(prompt, json_mode=True,
                                                         **call))
                except TypeError:
                    pass  # router has no json_mode — fall through
            return _as_text(self.router.generate(prompt, **call))
        except Exception:
            return ""


def _as_text(result: Any) -> str:
    """Normalise a router reply (dict or str) to the raw-text contract."""
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        if result.get("ok") is False:
            return ""
        text = result.get("text")
        if text is None:
            text = result.get("content") or result.get("message") or ""
        return str(text)
    return str(result)


def adapt_llm(llm: Any, *, role: str = "fast", system: str = "") -> Any:
    """Return ``llm`` unchanged if it already matches the jury contract.

    A caller-supplied test double with ``generate(prompt, json_mode=...)``
    returning a string is left alone (so existing tests keep working); anything
    else (dict-returning router, ``None``) is wrapped.
    """
    if llm is None:
        return None
    gen = getattr(llm, "generate", None)
    if gen is None:
        return RouterLLMAdapter(llm, role=role, system=system)
    try:
        probe = gen("", json_mode=True, temperature=0.0)
    except TypeError:
        return RouterLLMAdapter(llm, role=role, system=system)
    except Exception:
        return llm  # contract-correct object that merely raised on a probe
    return llm if isinstance(probe, str) else RouterLLMAdapter(
        llm, role=role, system=system)
