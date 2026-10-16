"""Coverage-gap tests for the infrastructure layers.

Targets the defensive/rare branches that the feature suites never touch:
a monitor that cannot write its log file, a monitoring patch whose monitor
raises, a checkpoint file holding valid-but-wrong JSON, a pipeline save with no
run id, the security grade floor, a skill file without a heading, and the
web dashboard's "dotenv missing" fallback.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from src.agents.base import BaseAgent
from src.core.backend import EchoBackend
from src.core.types import AgentResult
from src.nexus.monitoring import Monitor
from src.patterns.checkpoint import CheckpointStore
from src.patterns.pipeline import Pipeline
from src.security.scoring import grade_for
from src.skills.loader import SkillLoader

ROOT = Path(__file__).resolve().parents[1]


class _ExplodingMonitor:
    """A monitor whose ``log_call`` blows up (simulates a broken sink)."""

    def log_call(self, **kwargs: Any) -> None:
        raise RuntimeError("monitor sink down")


class _Echo(BaseAgent):
    name = "echo"
    group = "core"


# ── nexus/monitoring ─────────────────────────────────────────────────────
def test_monitor_log_call_survives_unwritable_file(tmp_path: Path) -> None:
    """A failed log write must be swallowed; the call stays in memory."""

    monitor = Monitor(str(tmp_path))
    blocker = tmp_path / "not-a-file"
    blocker.mkdir()
    monitor._today_file = str(blocker)  # open(..., "a") on a directory fails

    call = monitor.log_call(
        provider="groq", model="m", elapsed=0.25, ok=True, prompt="hi", response="ok"
    )

    assert call.ok is True
    assert monitor._session_calls == [call]
    assert monitor.get_session_stats()["total_calls"] == 1


def test_monitor_today_stats_skip_blank_lines(tmp_path: Path) -> None:
    """Blank lines in the journal are skipped, real calls still counted."""

    monitor = Monitor(str(tmp_path))
    monitor.log_call(provider="groq", model="m", elapsed=0.5, ok=True, prompt="abcdefgh")
    journal = Path(monitor._today_file)
    journal.write_text(journal.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")

    stats = monitor.get_today_stats()

    assert stats["total_calls"] == 1
    assert stats["successes"] == 1


def test_monitor_clear_today_reports_count(tmp_path: Path) -> None:
    """``clear_today`` returns the number of removed entries (0 when absent)."""

    monitor = Monitor(str(tmp_path))
    assert monitor.clear_today() == 0
    monitor.log_call(provider="groq", model="m", elapsed=0.1, ok=True, prompt="a")
    assert monitor.clear_today() == 1
    assert monitor.clear_today() == 0


# ── nexus/monitoring_patch ───────────────────────────────────────────────
def test_monitoring_patch_swallows_monitor_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken monitor must never break the wrapped LLM call (either path)."""

    import src.nexus.monitoring as monitoring
    import src.nexus.monitoring_patch as patch_module
    from novamind.core.llm_router import LLMRouter

    monkeypatch.setattr(monitoring, "get_monitor", lambda: _ExplodingMonitor())

    # -- success path: the monitor raises while logging the result ----------
    monkeypatch.setattr(patch_module, "_patched", False)
    monkeypatch.setattr(
        LLMRouter,
        "generate",
        lambda self, **kwargs: {"ok": True, "provider": "groq", "model": "m", "text": "hi"},
    )
    assert patch_module.patch_llm_router() is True
    result = LLMRouter.generate(object(), prompt="hello")  # type: ignore[arg-type]
    assert result == {"ok": True, "provider": "groq", "model": "m", "text": "hi"}

    # -- error path: the monitor raises while logging the failure -----------
    monkeypatch.setattr(patch_module, "_patched", False)

    def _boom(self: Any, **kwargs: Any) -> Any:
        raise RuntimeError("provider down")

    monkeypatch.setattr(LLMRouter, "generate", _boom)
    assert patch_module.patch_llm_router() is True
    with pytest.raises(RuntimeError, match="provider down"):
        LLMRouter.generate(object(), prompt="hello")  # type: ignore[arg-type]


# ── patterns ─────────────────────────────────────────────────────────────
def test_checkpoint_store_ignores_non_object_json(tmp_path: Path) -> None:
    """A journal holding a JSON array (not an object) loads as empty."""

    path = tmp_path / "checkpoints.json"
    path.write_text("[]", encoding="utf-8")

    store = CheckpointStore(path)

    assert store.runs() == []
    assert len(store) == 0


def test_pipeline_save_is_a_noop_without_a_run_id() -> None:
    """``_save`` must bail out when the run is not resumable."""

    pipeline = Pipeline([_Echo(EchoBackend())])
    pipeline._save(None, 0, AgentResult(agent="echo", ok=True, output="x"))

    assert pipeline._checkpoints is None


# ── security/scoring ─────────────────────────────────────────────────────
def test_grade_for_negative_score_is_the_floor() -> None:
    """The lowest grade is also the floor for out-of-range input."""

    assert grade_for(0) == "F"
    assert grade_for(-1) == "F"


# ── skills/loader ────────────────────────────────────────────────────────
def test_skill_loader_without_heading_has_no_description(tmp_path: Path) -> None:
    """A SKILL.md with no heading loads with an empty description."""

    skill_dir = tmp_path / "plain"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("just prose\nno heading here\n", encoding="utf-8")

    loader = SkillLoader(tmp_path)
    skill = loader.load("plain")

    assert skill is not None
    assert skill.description == ""
    assert "just prose" in skill.content


def test_skill_loader_reads_the_first_heading(tmp_path: Path) -> None:
    """The first heading wins; prose before it is skipped."""

    skill_dir = tmp_path / "headed"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("prose first\n# The Real Title\nbody\n", encoding="utf-8")

    skill = SkillLoader(tmp_path).load("headed")

    assert skill is not None
    assert skill.description == "The Real Title"


# ── web/app ──────────────────────────────────────────────────────────────
def test_web_app_loads_without_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """The dashboard must import cleanly when ``python-dotenv`` is absent."""

    source_path = ROOT / "src" / "web" / "app.py"
    source = source_path.read_text(encoding="utf-8")
    monkeypatch.setitem(sys.modules, "dotenv", None)

    namespace: dict[str, Any] = {
        "__name__": "src.web.app_no_dotenv",
        "__file__": str(source_path),
    }
    exec(compile(source, str(source_path), "exec"), namespace)

    assert namespace["app"].title == "Nexus-Core Dashboard"
