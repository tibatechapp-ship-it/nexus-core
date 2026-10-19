"""Phase 2 Day 3 — hermetic tests for the collaboration primitives.

Everything runs offline: every LLM-shaped dependency (``classifier``,
``ask_fn``, ``synthesize_fn``, the default router) is injected or faked.
"""

from __future__ import annotations

import sys
import types
from typing import Any

from src.learning import collab
from src.learning.collab import (
    CATEGORIES,
    classify_question,
    consult,
    multi_agent_consensus,
)


# ---------------------------------------------------------------- classify --

def test_classify_five_categories_via_the_keyword_fallback() -> None:
    cases = {
        "كيف أصلح خطأ في دالة بايثون ترجع قيماً خاطئة؟": "technical",
        "حلل بيانات المبيعات وقارنها بالربع الماضي": "analytical",
        "ما استراتيجيتنا للتوسع في السوق السعودي؟": "strategic",
        "نقد هذه الخطة وحدد أوجه الضعف": "critical",
        "نظّم جدول مهام الفريق للأسبوع القادم": "organizational",
    }
    assert set(cases.values()) == set(CATEGORIES)
    for question, expected in cases.items():
        assert classify_question(question, classifier=lambda q: q) == expected


def test_classify_accepts_an_english_slug_from_the_classifier() -> None:
    out = classify_question("أي شيء", classifier=lambda q: "The category is: strategic")
    assert out == "strategic"


def test_classify_accepts_an_arabic_label_from_the_classifier() -> None:
    assert classify_question("أي شيء", classifier=lambda q: "الفئة: تقني") == "technical"


def test_classify_default_routes_through_the_llm(monkeypatch) -> None:
    monkeypatch.setattr(collab, "_llm_classify", lambda q: "organizational")
    assert classify_question("أي شيء") == "organizational"


def test_classify_default_degrades_to_keywords_when_the_llm_fails(monkeypatch) -> None:
    def boom(question: str) -> str:
        raise RuntimeError("no router here")

    monkeypatch.setattr(collab, "_llm_classify", boom)
    assert classify_question("أضف دالة بايثون جديدة") == "technical"


def test_classify_unmatched_text_falls_back_to_analytical() -> None:
    assert classify_question("مرحبا", classifier=lambda q: q) == "analytical"


def test_llm_classify_calls_the_router_with_the_system_prompt(monkeypatch) -> None:
    holder: dict[str, Any] = {}

    class _FakeRouter:
        def __init__(self) -> None:
            holder["built"] = True

        def generate(self, prompt: str, system: str = "", role: str = "fast",
                     **kwargs: object) -> str:
            holder["args"] = (prompt, system, role)
            return "analytical"

    fake_module = types.ModuleType("novamind.core.llm_router")
    fake_module.LLMRouter = _FakeRouter  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "novamind", types.ModuleType("novamind"))
    monkeypatch.setitem(sys.modules, "novamind.core", types.ModuleType("novamind.core"))
    monkeypatch.setitem(sys.modules, "novamind.core.llm_router", fake_module)

    out = collab._llm_classify("سؤال الاختبار")
    assert out == "analytical"
    assert holder["built"] is True
    prompt, system, role = holder["args"]  # type: ignore[misc]
    assert prompt == "سؤال الاختبار"
    assert "technical" in system and "organizational" in system
    assert role == "fast"


# ------------------------------------------------------------------ consult --

def test_consult_success_returns_the_first_answer() -> None:
    calls: list[tuple[str, str]] = []

    def ask(agent: str, prompt: str) -> str:
        calls.append((agent, prompt))
        return "الإجابة الأولى" if agent == "primary" else "الإجابة مقبولة"

    result = consult("primary", "critic", "ما هو X؟", ask_fn=ask)
    assert set(result) == {"answer", "critique", "retries", "final_answer"}
    assert result["answer"] == "الإجابة الأولى"
    assert result["critique"] == "الإجابة مقبولة"
    assert result["retries"] == 0
    assert result["final_answer"] == "الإجابة الأولى"
    assert [agent for agent, _ in calls] == ["primary", "critic"]


def test_consult_revises_once_when_the_critique_flags_a_flaw() -> None:
    critiques = ["وجدت خطأ في المنطق", "الآن الإجابة سليمة"]
    state: dict[str, Any] = {"n": 0, "asks": []}

    def ask(agent: str, prompt: str) -> str:
        state["asks"].append((agent, prompt))
        if agent == "primary":
            return "محاولة أولى" if state["n"] == 0 else "محاولة محسّنة"
        text = critiques[min(state["n"], len(critiques) - 1)]
        state["n"] += 1
        return text

    result = consult("primary", "critic", "سؤال", ask_fn=ask)
    assert result["retries"] == 1
    assert result["final_answer"] == "محاولة محسّنة"
    assert result["critique"] == "الآن الإجابة سليمة"
    assert [agent for agent, _ in state["asks"]] == ["primary", "critic",
                                                     "primary", "critic"]
    revise_prompt = state["asks"][2][1]
    assert "ملاحظات الناقد" in revise_prompt
    assert "خطأ" in revise_prompt


def test_consult_zero_retries_never_revises() -> None:
    def ask(agent: str, prompt: str) -> str:
        return "الأولى" if agent == "primary" else "فيه ضعف"

    result = consult("primary", "critic", "سؤال", ask_fn=ask, max_retries=0)
    assert result["retries"] == 0
    assert result["final_answer"] == "الأولى"


def test_consult_multi_round_up_to_max_retries() -> None:
    critiques = ["ضعف بسيط", "لا يزال ضعف", "ممتاز الآن"]
    state = {"n": 0}

    def ask(agent: str, prompt: str) -> str:
        if agent == "primary":
            return f"محاولة {state['n']}"
        text = critiques[state["n"]]
        state["n"] += 1
        return text

    result = consult("primary", "critic", "سؤال", ask_fn=ask, max_retries=2)
    assert result["retries"] == 2
    assert result["final_answer"] == "محاولة 2"
    assert result["critique"] == "ممتاز الآن"


# ----------------------------------------------------------------- consensus --

def test_consensus_three_agents() -> None:
    def ask(agent: str, question: str) -> str:
        return f"إجابة {agent}"

    def synthesize(question: str, answers: list[str]) -> str:
        return " || ".join(answers)

    result = multi_agent_consensus(
        "سؤال", ["a1", "a2", "a3"], ask_fn=ask, synthesize_fn=synthesize,
    )
    assert result["agents_used"] == ["a1", "a2", "a3"]
    assert result["consensus"] == "إجابة a1 || إجابة a2 || إجابة a3"
    assert result["individual_answers"] == [
        {"agent": "a1", "answer": "إجابة a1"},
        {"agent": "a2", "answer": "إجابة a2"},
        {"agent": "a3", "answer": "إجابة a3"},
    ]


def test_consensus_skips_a_failing_agent() -> None:
    def ask(agent: str, question: str) -> str:
        if agent == "dead":
            raise RuntimeError("agent down")
        return f"من {agent}"

    result = multi_agent_consensus(
        "سؤال", ["ok1", "dead", "ok2"],
        ask_fn=ask, synthesize_fn=lambda q, a: "|".join(a),
    )
    assert result["agents_used"] == ["ok1", "ok2"]
    assert [item["agent"] for item in result["individual_answers"]] == ["ok1", "ok2"]


def test_consensus_empty_when_nobody_answers() -> None:
    synthesize_calls: list[object] = []

    def ask(agent: str, question: str) -> str:
        raise RuntimeError("agent down")

    def synthesize(question: str, answers: list[str]) -> str:
        synthesize_calls.append(answers)
        return "لا شيء"

    result = multi_agent_consensus("سؤال", ["a", "b"], ask_fn=ask,
                                   synthesize_fn=synthesize)
    assert result == {"consensus": "", "individual_answers": [], "agents_used": []}
    assert synthesize_calls == []

    empty = multi_agent_consensus("سؤال", [], ask_fn=lambda a, q: "لا",
                                  synthesize_fn=synthesize)
    assert empty["agents_used"] == []


def test_consensus_synthesis_failure_degrades_to_a_plain_join() -> None:
    def ask(agent: str, question: str) -> str:
        return f"من {agent}"

    def synthesize(question: str, answers: list[str]) -> str:
        raise RuntimeError("synth down")

    result = multi_agent_consensus("سؤال", ["x", "y"], ask_fn=ask,
                                   synthesize_fn=synthesize)
    assert result["consensus"] == "من x\nمن y"
    assert result["agents_used"] == ["x", "y"]
