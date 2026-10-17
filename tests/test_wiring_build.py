"""Wiring tests: the Builder blueprint prompt carries the knowledge base (P2).

``src.council.builder._compose_blueprint_prompt`` must prepend the project
knowledge block to the builder instructions before the LLM call, and degrade
gracefully (instructions + question, no knowledge) if the layer is missing.

Hermetic: pure functions + a fake knowledge layer; no provider needed.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.council.builder import Builder, _compose_blueprint_prompt

_KB_HEADER = "### قاعدة المعرفة المشتركة (Knowledge Base)"
_FALLBACK_SPLIT = "\n\nالسؤال: "


def test_compose_prepends_instructions_and_appends_question() -> None:
    """The composed prompt = instructions … knowledge … question (via inject)."""
    out = _compose_blueprint_prompt("INSTRUCTIONS HERE", "build me a thing")
    assert out.startswith("INSTRUCTIONS HERE")
    assert _KB_HEADER in out
    assert out.index(_KB_HEADER) < out.index("### المهمّة")
    assert out.rstrip().endswith("build me a thing")


def test_compose_falls_back_when_knowledge_layer_breaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken knowledge layer degrades to instructions + question, no raise."""
    def _boom(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("knowledge layer down")

    monkeypatch.setattr("src.knowledge.inject_into_prompt", _boom)
    out = _compose_blueprint_prompt("INSTR", "the question")
    assert out == f"INSTR{_FALLBACK_SPLIT}the question"


def test_compose_falls_back_when_knowledge_import_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``src.knowledge`` cannot be imported, still fall back cleanly."""
    import builtins

    real_import = builtins.__import__

    def _guard(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "src.knowledge":
            raise ImportError("no knowledge package")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guard)
    out = _compose_blueprint_prompt("INSTR", "the question")
    assert out == f"INSTR{_FALLBACK_SPLIT}the question"


def test_blueprint_prompt_routes_through_the_knowledge_injector() -> None:
    """``_blueprint_prompt`` emits the KB block + the question + the council line."""
    builder = Builder()
    result = {
        "transcript": [{"verdict": "نعم", "reasoning": "y"}],
        "verdict": "approve",
    }
    prompt = builder._blueprint_prompt("ابنِ خدمة صغيرة", result)
    assert _KB_HEADER in prompt
    assert "### المهمّة\nابنِ خدمة صغيرة" in prompt
    assert "قرار المجلس: approve" in prompt


def test_blueprint_prompt_without_recommendation_still_composes() -> None:
    """An empty transcript yields the '(لا توصية)' placeholder, still knowledge-augmented."""
    builder = Builder()
    prompt = builder._blueprint_prompt("q", {"transcript": [], "verdict": "reject"})
    assert "(لا توصية)" in prompt
    assert _KB_HEADER in prompt
