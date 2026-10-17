"""Tests for the skills-first chat wiring (layer 3 in ``_agent_system``).

``nexus_agent._agent_system`` must compose: agent prompt + knowledge block +
**skills block** (the agent's manifest skills). It must never break chat if the
skills layer is unavailable.

Hermetic: the gateway is loaded by path; the knowledge singleton points at a
temp corpus; no provider is ever called.
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
_SKILLS_HEADER = "### المهارات المُفعَّلة (Skills)"


def _load_unified() -> Any:
    """Load the repo-root ``nexus_agent.py`` by path (fresh module per call)."""
    spec = importlib.util.spec_from_file_location(
        "nexus_unified_skills_wiring", _ROOT / "nexus_agent.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["nexus_unified_skills_wiring"] = module  # Pydantic forward refs
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
    monkeypatch.setattr(
        "src.knowledge.base.get_knowledge_base",
        lambda: KnowledgeBase(seed, tmp_path / "user"),
    )
    return _load_unified()


def test_agent_system_injects_the_skills_block(unified: Any) -> None:
    """The agent's own manifest skills appear in the composed system prompt."""
    from src.agents.manifest import get_manifest

    skills = get_manifest("coder").skills
    assert skills, "coder should declare at least one skill"
    system = unified._agent_system("coder", "add a --dry-run flag")
    assert _SKILLS_HEADER in system
    assert skills[0] in system


def test_agent_system_keeps_the_knowledge_block_too(unified: Any) -> None:
    """Both layers compose — knowledge stays, skills are appended after it."""
    system = unified._agent_system("coder", "task")
    assert _KB_HEADER in system
    assert _SKILLS_HEADER in system
    assert system.index(_KB_HEADER) < system.index(_SKILLS_HEADER)


def test_agent_system_unknown_agent_has_no_skills(unified: Any) -> None:
    """An unknown agent id has no manifest, so no skills block (KB still there)."""
    system = unified._agent_system("does-not-exist", "task")
    assert _KB_HEADER in system
    assert _SKILLS_HEADER not in system


def test_agent_system_falls_back_when_skills_unavailable(
    unified: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken skills layer degrades to the knowledge-only prompt — never raises."""
    def _boom(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("skills layer down")

    monkeypatch.setattr("src.skills.inject_skills_into_prompt", _boom)
    system = unified._agent_system("coder", "task")
    assert _SKILLS_HEADER not in system
    assert _KB_HEADER in system


def test_engine_mounts_the_skills_routes(unified: Any) -> None:
    """The gateway's engine really serves ``/api/skills/*`` (wiring, not dead code)."""
    assert unified.ENGINE_OK, unified.ENGINE_ERR
    paths = {getattr(route, "path", None) for route in unified._engine.app.router.routes}
    assert "/api/skills" in paths
    assert "/api/skills/{name}" in paths
