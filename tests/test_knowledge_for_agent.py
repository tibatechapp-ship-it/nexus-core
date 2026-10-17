"""Tests for knowledge selection, category docs and prompt injection (P2).

Hermetic: throwaway ``tmp_path`` dirs, no real home, no network. The composed
prompt is the contract — order matters (instructions → knowledge → task).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.knowledge.base import UNIVERSAL_DOCS, KnowledgeBase
from src.knowledge.inject import (
    agent_category,
    agent_name,
    agent_prompt,
    inject_into_prompt,
    knowledge_block,
)


#────────────────────────────── helpers ──────────────────────────────#


def _write(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    return path


def _seed(directory: Path) -> None:
    """A minimal corpus: 2 universal (pinned) + a category doc + a plain doc."""
    _write(directory, "nexus-core", "---\ntitle: Nexus\ncategory: core\n---\nproject\n")
    _write(directory, "conventions", "---\ntitle: Conventions\ncategory: core\n---\nstyle\n")
    _write(
        directory,
        "quality-rules",
        "---\ntitle: Quality\ntags: quality, tests\n---\nwrite tests\n",
    )
    _write(directory, "notes", "---\ntitle: Notes\ncategory: misc\n---\nscratch\n")


@pytest.fixture()
def kb(tmp_path: Path) -> KnowledgeBase:
    seed = tmp_path / "seed"
    _seed(seed)
    return KnowledgeBase(seed, tmp_path / "user")


class _Agent:
    """Stand-in for a BaseAgent (name/group/system_prompt)."""

    def __init__(self, name: str, group: str = "", prompt: str = "") -> None:
        self.name = name
        self.group = group
        self.system_prompt = prompt


#────────────────────────── category / selection ───────────────────────────#


def test_select_leads_with_the_universal_docs(kb: KnowledgeBase) -> None:
    """The universal docs are always first, in their declared order."""
    names = [doc.name for doc in kb.select("coder", "anything")]
    assert names[: len(UNIVERSAL_DOCS)] == list(UNIVERSAL_DOCS)


def test_select_limit_zero_is_empty(kb: KnowledgeBase) -> None:
    """``limit <= 0`` yields no docs (guard before any work)."""
    assert kb.select("coder", "anything", limit=0) == []
    assert kb.select("coder", "anything", limit=-3) == []


def test_select_dedupes_a_pinned_universal_doc(kb: KnowledgeBase) -> None:
    """A doc that is both universal and pinned appears exactly once."""
    names = [doc.name for doc in kb.select("coder", "anything", limit=10)]
    assert names.count("nexus-core") == 1


def test_select_honours_the_limit(kb: KnowledgeBase) -> None:
    """Never returns more than ``limit`` docs."""
    assert len(kb.select("coder", "quality tests", limit=2)) == 2


def test_select_missing_universal_docs_are_skipped(tmp_path: Path) -> None:
    """A base with neither universal doc still selects a relevant doc."""
    empty = KnowledgeBase(tmp_path / "seed", tmp_path / "user")
    _write(tmp_path / "seed", "solo", "---\ntitle: Solo\n---\nbody\n")
    names = [doc.name for doc in empty.select("coder", "solo")]
    assert names == ["solo"]


#────────────────────────────── category_doc ──────────────────────────────#


def test_category_doc_matches_by_category(kb: KnowledgeBase) -> None:
    """An explicit category key is matched first."""
    doc = kb.category_doc("whatever", "misc")
    assert doc is not None and doc.name == "notes"


def test_category_doc_matches_by_tag(kb: KnowledgeBase) -> None:
    """No category match → fall back to a tag match."""
    doc = kb.category_doc("quality", "")
    assert doc is not None and doc.name == "quality-rules"


def test_category_doc_matches_by_doc_name(kb: KnowledgeBase) -> None:
    """A doc whose name equals the key is matched."""
    doc = kb.category_doc("conventions", "")
    assert doc is not None and doc.name == "conventions"


def test_category_doc_missing_returns_none(kb: KnowledgeBase) -> None:
    """No category, name or tag match → None (not an exception)."""
    assert kb.category_doc("nobody", "nothing") is None


def test_category_doc_blank_keys_are_ignored(kb: KnowledgeBase) -> None:
    """Whitespace-only keys are skipped; a valid fallback still wins."""
    doc = kb.category_doc("  ", "misc")
    assert doc is not None and doc.name == "notes"


def test_select_injects_the_category_doc(kb: KnowledgeBase) -> None:
    """The agent's category doc rides along after the universal docs."""
    names = [doc.name for doc in kb.select("x", "", limit=10, category="misc")]
    assert "notes" in names


#────────────────────────────── for_agent ──────────────────────────────#


def test_for_agent_contains_its_category_block(kb: KnowledgeBase) -> None:
    """``for_agent`` with a category renders that doc's body."""
    text = kb.for_agent("x", "", category="misc")
    assert "scratch" in text
    assert "Knowledge Base" in text


def test_for_agent_empty_base_is_empty_string(tmp_path: Path) -> None:
    """No docs at all → empty string (not a header with no content)."""
    empty = KnowledgeBase(tmp_path / "seed", tmp_path / "user")
    assert empty.for_agent("coder", "task") == ""


#───────────────────────────── agent helpers ─────────────────────────────#


def test_agent_name_from_string_and_object() -> None:
    """A bare string is the agent id; an object reads name/id/agent_id."""
    assert agent_name("coder") == "coder"
    assert agent_name(_Agent("tester")) == "tester"
    assert agent_name(object())  # falls back to the class name, non-empty


def test_agent_name_reads_alternative_attrs() -> None:
    """``.id`` / ``.agent_id`` are accepted when ``.name`` is absent."""

    class _ById:
        id = "planner"

    assert agent_name(_ById()) == "planner"


def test_agent_prompt_prefers_system_prompt() -> None:
    """The system prompt is the instruction text (empty for a bare string)."""
    assert agent_prompt(_Agent("x", prompt="  be careful  ")) == "be careful"
    assert agent_prompt("coder") == ""


def test_agent_prompt_falls_back_to_identity() -> None:
    """No ``system_prompt`` → use ``identity``."""

    class _Ident:
        identity = "quality guardian"

    assert agent_prompt(_Ident()) == "quality guardian"


def test_agent_category_reads_group() -> None:
    """Category = the agent's group; blank when absent."""
    assert agent_category(_Agent("x", group="quality")) == "quality"
    assert agent_category("coder") == ""


#────────────────────────── inject_into_prompt ───────────────────────────#


def test_inject_orders_instructions_then_knowledge_then_task(kb: KnowledgeBase) -> None:
    """Sections appear in the fixed order, joined by a blank line."""
    agent = _Agent("coder", group="quality", prompt="You are the coder.")
    out = inject_into_prompt(agent, "fix the bug", kb=kb)
    assert out.startswith("You are the coder.")
    assert out.index("Knowledge Base") < out.index("### المهمّة")
    assert out.rstrip().endswith("fix the bug")
    assert "You are the coder.\n\n### قاعدة المعرفة" in out


def test_inject_without_prompt_or_task_keeps_only_knowledge(kb: KnowledgeBase) -> None:
    """Empty prompt and empty task → just the knowledge block, no headers."""
    out = inject_into_prompt("coder", "   ", kb=kb)
    assert "Knowledge Base" in out
    assert "### المهمّة" not in out


def test_inject_strips_the_task(kb: KnowledgeBase) -> None:
    """A task with surrounding whitespace is trimmed in the output."""
    out = inject_into_prompt(_Agent("coder"), "  ship it  ", kb=kb)
    assert "### المهمّة\nship it" in out


def test_inject_uses_the_live_singleton_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without ``kb=`` the module singleton is used (and its docs injected)."""
    seed = tmp_path / "seed"
    _seed(seed)
    monkeypatch.setattr(
        "src.knowledge.base.get_knowledge_base",
        lambda: KnowledgeBase(seed, tmp_path / "user"),
    )
    out = inject_into_prompt("coder", "do work")
    assert "Knowledge Base" in out


def test_inject_accepts_any_agent_like_object(kb: KnowledgeBase) -> None:
    """A duck-typed object with the right attrs works (no BaseAgent import)."""

    class _Duck:
        name = "planner"
        group = "quality"
        identity = "planner identity"

    out = inject_into_prompt(_Duck(), "plan it", kb=kb)
    assert out.startswith("planner identity")
    assert "plan it" in out


def test_inject_returns_task_only_without_docs(tmp_path: Path) -> None:
    """An empty KB still yields the task section (never a bare empty blob)."""
    empty = KnowledgeBase(tmp_path / "seed", tmp_path / "user")
    out = inject_into_prompt("coder", "only task", kb=empty)
    assert out == "### المهمّة\nonly task"


def test_inject_kb_param_types_are_duck_checked() -> None:
    """The signature accepts a plain str agent and an int limit."""
    out = inject_into_prompt("coder", "t", kb=_EmptyKB(), limit=1)  # type: ignore[arg-type]
    assert "t" in out


class _EmptyKB:
    """Minimal duck-typed KB returning no knowledge."""

    def for_agent(self, agent_id: str, task: str, limit: int, category: str) -> str:
        return ""

    # ``inject_into_prompt`` only calls ``for_agent``.
    def __getattr__(self, item: str) -> Any:  # pragma: no cover - not reached
        raise AttributeError(item)


#──────────────────────── knowledge_block (P2 wiring) ─────────────────────────#


def test_knowledge_block_is_the_bare_block(kb: KnowledgeBase) -> None:
    """``knowledge_block`` returns only the KB block (no task/instructions)."""
    out = knowledge_block(_Agent("coder", group="quality"), "fix the bug", kb=kb)
    assert out.startswith("### قاعدة المعرفة")
    assert "### المهمّة" not in out


def test_knowledge_block_empty_corpus_is_empty(tmp_path: Path) -> None:
    empty = KnowledgeBase(tmp_path / "seed", tmp_path / "user")
    assert knowledge_block("coder", "t", kb=empty) == ""


#────────────────── instructions override + include_task (P2 wiring) ──────────#


def test_inject_instructions_override_beats_the_agent_prompt(kb: KnowledgeBase) -> None:
    """``instructions=`` replaces the agent prompt with the caller's text."""
    agent = _Agent("coder", prompt="IGNORED PROMPT")
    out = inject_into_prompt(agent, "task here", kb=kb, instructions="CALLER TEXT")
    assert out.startswith("CALLER TEXT")
    assert "IGNORED PROMPT" not in out
    assert out.rstrip().endswith("task here")


def test_inject_include_task_false_drops_the_task_section(kb: KnowledgeBase) -> None:
    """``include_task=False`` uses the task for selection but never copies it."""
    agent = _Agent("coder", prompt="You are the coder.")
    out = inject_into_prompt(agent, "secret task text", kb=kb, include_task=False)
    assert out.startswith("You are the coder.")
    assert "Knowledge Base" in out
    assert "### المهمّة" not in out
    assert "secret task text" not in out


def test_inject_include_task_false_without_knowledge_is_empty(tmp_path: Path) -> None:
    """No instructions, no knowledge, no task section → empty string."""
    empty = KnowledgeBase(tmp_path / "seed", tmp_path / "user")
    out = inject_into_prompt("coder", "t", kb=empty, include_task=False)
    assert out == ""


def test_inject_blank_instructions_falls_back_to_no_heading(kb: KnowledgeBase) -> None:
    """A whitespace-only ``instructions`` is dropped (no empty heading)."""
    out = inject_into_prompt(_Agent("coder"), "task", kb=kb, instructions="   ")
    assert out.startswith("### قاعدة المعرفة")
    assert out.rstrip().endswith("task")
