"""nexus-core — unified AI agent system (memory + learning + security + 20 agents).

This package layers a multi-agent system and an interactive TUI on top of the
local ZYVO HTTP API. The two original standalone assistants
(``zyvo-telegram.py`` and ``zyvo-voice.py``) remain untouched at the repository
root; everything under ``src/`` is importable.

Import layout::

    src.core       → message types, LLM backend protocol, ZYVO HTTP client
    src.agents     → BaseAgent, AgentRegistry, AgentState, AgentMetrics
    src.patterns   → Supervisor, Pipeline, Fanout, Delegation, Blackboard
    src.memory     → episodic/semantic/procedural/emotional stores + manager
    src.learning   → ExperienceCollector (what agents did + how it ended)
    src.security   → offline static security scanner (agents + classifier)
    src.tui        → terminal UI (Textual app + screens + widgets)
    src.novamind   → former novamind orchestration package (opt-in extras)
"""

from __future__ import annotations

import tomllib
from pathlib import Path


def _read_version() -> str:
    """الإصدار من مصدر واحد: ``pyproject.toml`` — لا تكرار يدوي.

    يُقرأ عند الاستيراد من ملف المشروع؛ إن غاب (مثلاً حزمة مثبّتة بلا
    pyproject) نعود إلى ``"0.0.0"`` بدل رقم قديم يتقادم.
    """
    try:
        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        with pyproject.open("rb") as fh:
            return str(tomllib.load(fh)["project"]["version"])
    except Exception:  # pragma: no cover - defensive (no pyproject next to src/)
        return "0.0.0"


__version__ = _read_version()

__all__ = ["__version__"]
