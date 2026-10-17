"""Wiring tests: the chat path carries the shared knowledge base (P2 wiring).

``nexus_agent._agent_system`` must compose the agent's system prompt with the
project knowledge block (so ``/api/chat`` answers with project awareness), and
it must NEVER break chat if the knowledge layer is unavailable — a failure falls
back to the plain system prompt.

Hermetic: the module is loaded by path; nothing calls a real provider.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sse_starlette")
pytest.importorskip("httpx")

from src.knowledge.base import KnowledgeBase  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
_KB_HEADER = "### قاعدة المعرفة المشتركة (Knowledge Base)"


def _load_unified() -> Any:
    """Load the repo-root ``nexus_agent.py`` by path (fresh module per call)."""
    spec = importlib.util.spec_from_file_location(
        "nexus_unified_chat_wiring", _ROOT / "nexus_agent.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["nexus_unified_chat_wiring"] = module  # Pydantic forward refs
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def unified(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """A loaded gateway whose knowledge singleton points at a temp corpus."""
    seed = tmp_path / "seed"
    seed.mkdir(parents=True, exist_ok=True)
    (seed / "nexus-core.md").write_text(
        "---\ntitle: Nexus\ncategory: core\n---\nproject rules\n", encoding="utf-8"
    )
    (seed / "conventions.md").write_text(
        "---\ntitle: Conventions\n---\nstyle rules\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "src.knowledge.base.get_knowledge_base",
        lambda: KnowledgeBase(seed, tmp_path / "user"),
    )
    return _load_unified()


def test_agent_system_injects_the_knowledge_block(unified: Any) -> None:
    """The knowledge base is appended to the agent's system prompt."""
    system = unified._agent_system("coder", "add a --dry-run flag")
    assert _KB_HEADER in system
    # ``include_task=False``: the raw task is never copied into the system text.
    assert "add a --dry-run flag" not in system


def test_agent_system_keeps_the_agent_prompt(unified: Any) -> None:
    """A known agent's own system prompt still heads the composed text."""
    cls = unified._agent_for("coder")
    assert cls is not None
    prompt = getattr(cls, "system_prompt", "") or unified._DEFAULT_SYSTEM
    system = unified._agent_system("coder", "anything")
    assert system.startswith(prompt)
    assert _KB_HEADER in system


def test_agent_system_unknown_agent_falls_back_to_default(unified: Any) -> None:
    """An unknown agent id still gets the default prompt + knowledge."""
    system = unified._agent_system("does-not-exist", "task")
    assert system.startswith(unified._DEFAULT_SYSTEM)
    assert _KB_HEADER in system


def test_agent_system_no_agent_uses_default_with_knowledge(unified: Any) -> None:
    """``agent=None`` → default prompt, still knowledge-augmented."""
    system = unified._agent_system(None, "task")
    assert system.startswith(unified._DEFAULT_SYSTEM)
    assert _KB_HEADER in system


def test_agent_system_falls_back_when_knowledge_unavailable(
    unified: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken knowledge layer degrades to the plain prompt — never raises."""
    def _boom(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("knowledge layer down")

    monkeypatch.setattr("src.knowledge.inject_into_prompt", _boom)
    cls = unified._agent_for("coder")
    prompt = getattr(cls, "system_prompt", "") or unified._DEFAULT_SYSTEM
    assert unified._agent_system("coder", "task") == prompt


def test_agent_for_is_none_for_blank_id(unified: Any) -> None:
    """``_agent_for`` short-circuits a blank id without scanning the roster."""
    assert unified._agent_for("") is None
    assert unified._agent_for(None) is None


def test_chat_handler_passes_the_message_to_the_system(
    unified: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``api_chat`` hands the user message to ``_agent_system`` for selection.

    The system string is composed eagerly (before the SSE generator runs), so
    this proves the wiring lives in the live handler, not in dead helper code.
    """
    seen: dict[str, Any] = {}

    def _spy(agent_id: Any, task: str = "") -> str:
        seen["agent_id"] = agent_id
        seen["task"] = task
        return "SYSTEM"

    monkeypatch.setattr(unified, "_agent_system", _spy)
    req = unified.ChatRequest(message="  hello there  ", agent="coder")
    unified.api_chat(req)  # generator body is lazy; the system is composed now
    assert seen["agent_id"] == "coder"
    assert seen["task"] == "hello there"
