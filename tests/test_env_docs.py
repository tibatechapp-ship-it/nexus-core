"""Environment-variable documentation guard.

Every operator-facing env var the framework reads (``NEXUS_*``, ``CRAFT_*``,
``GROQ_*`` ...) must be documented in ``.env.example`` so the template never
drifts behind the code.  Deep ``src/novamind`` legacy internals and ad-hoc
script knobs are intentionally out of scope — the allowlists below name them so
the exclusion is explicit rather than accidental.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

_READ = re.compile(
    r"""os\.(?:getenv|environ\.get)\(\s*["']([A-Z][A-Z0-9_]*)["']"""
    r"""|os\.environ\[\s*["']([A-Z][A-Z0-9_]*)["']\s*\]""",
)

# Prefixes that represent operator-facing configuration.
_TRACKED_PREFIXES = ("NEXUS_", "CRAFT_", "GROQ_", "OLLAMA_", "NOVAMIND_", "ZYVO_")

# Vars read only from repo-internal scripts / CI tooling, deliberately not in
# the operator template.  Named so the exclusion is visible, not silent.
_ALLOWED_UNDOCUMENTED = frozenset(
    {
        "NEXUS_AGENT",  # scripts/_run_agent_with_rag.py ad-hoc
        "NEXUS_PROMPT",  # scripts/_run_agent_with_rag.py ad-hoc
        "NEXUS_RAG",  # scripts/_run_agent_with_rag.py ad-hoc
        "ZYVO_HEARTBEAT_INTERVAL",  # zyvo-*.py standalone assistants
        "ZYVO_MONITOR_LOG",
        "ZYVO_PORT",
        "ZYVO_SERVICE",
        "ZYVO_WATCHDOG_INTERVAL",
        "ZYVO_TELEGRAM_CHAT_ID",
        "NOVAMIND_PROJECT_ROOT",
        "NOVAMIND_SECURITY",
    }
)

# Legacy novamind internals (coverage-excluded) read many private knobs; they
# are not part of the operator contract.
_IGNORED_PATHS = ("src/novamind/", "tests/")


def _scan_sources() -> set[str]:
    found: set[str] = set()
    for path in _ROOT.rglob("*.py"):
        rel = path.relative_to(_ROOT).as_posix()
        if rel.startswith(_IGNORED_PATHS) or "/tests/" in rel:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in _READ.finditer(text):
            name = match.group(1) or match.group(2)
            if name.startswith(_TRACKED_PREFIXES):
                found.add(name)
    return found


def _documented() -> set[str]:
    text = (_ROOT / ".env.example").read_text(encoding="utf-8")
    return {m.group(1) for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=?", text, re.M)}


def test_every_tracked_env_var_is_documented() -> None:
    undocumented = sorted(_scan_sources() - _documented() - _ALLOWED_UNDOCUMENTED)
    assert not undocumented, (
        "These env vars are read by the framework but missing from .env.example: "
        f"{undocumented}. Document them, or add them to _ALLOWED_UNDOCUMENTED."
    )


def test_scanner_finds_known_vars() -> None:
    # Sanity: the scanner must actually detect real reads (guards against a
    # regex that silently matches nothing and the test passing vacuously).
    found = _scan_sources()
    assert "NEXUS_AUTH_TOKEN" in found
    assert "NEXUS_GENOME_PATH" in found
