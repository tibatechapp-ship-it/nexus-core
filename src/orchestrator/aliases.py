"""Verb aliases — deterministic routing help when keyword scores tie at zero.

The router scores a request by intersecting its tokens with each agent's
`scope`/`domain` words. A verb like "rotate" or "optimize" often shares no
word with any agent (score 0) and the tie-break silently hands the task to the
genome's favourite — an analyst that *plans* instead of an agent that *acts*.

This module expands each known verb into the domain words it implies, so the
router can score the request against those words too. Pure and stdlib-only:
no I/O, no LLM, no clock.
"""
from __future__ import annotations
import os
from typing import Dict, Iterable, Tuple

# verb -> domain keywords the verb implies (fed to the router as extra tokens)
ALIASES: Dict[str, Tuple[str, ...]] = {
    # engineering
    "optimize": ("optimize", "performance", "profile", "perf"),
    "refactor": ("refactor", "restructure", "code", "clean"),
    "debug": ("debug", "diagnose", "fix", "trace"),
    "implement": ("code", "write", "fix"),
    "code": ("code", "write", "implement"),
    "fix": ("fix", "bug", "diagnose", "debug"),
    "test": ("test", "tester", "pytest", "unit"),
    "review": ("review", "code review"),
    # ops
    "deploy": ("deploy", "devops", "ops", "release", "production"),
    "migrate": ("migration", "schema", "deploy", "devops"),
    "rollback": ("rollback", "restore", "recovery"),
    "restore": ("restore", "recovery", "rollback"),
    "monitor": ("monitor", "metrics", "alert", "watch"),
    # security / destructive
    "rotate": ("auth", "security", "token", "secret", "audit", "vulnerabilities"),
    "purge": ("delete", "remove", "recovery", "rollback", "restore"),
    "clean": ("clean", "purge", "remove", "recovery"),
    "remove": ("remove", "delete", "recovery", "restore"),
    "delete": ("delete", "remove", "purge", "recovery", "rollback", "restore"),
    "drop": ("delete", "remove", "recovery", "rollback"),
    "truncate": ("delete", "remove", "recovery", "rollback"),
    # docs / research
    "document": ("documentation", "docs", "docstring"),
    "explain": ("documentation", "summarize", "explain"),
    "summarize": ("summarize", "report", "reporter"),
    "research": ("research", "search", "fact-check"),
    "analyze": ("analyze", "analysis", "pattern", "data"),
    # design / planning
    "design": ("design", "architecture", "ui", "ux"),
    "plan": ("plan", "planner", "breakdown", "tasks"),
    "estimate": ("estimate", "effort", "cost"),
}

_OFF = {"0", "off", "no", "false"}


def aliases_enabled() -> bool:
    """Feature flag: `NEXUS_ALIASES=0` disables expansion (old behaviour)."""
    return os.environ.get("NEXUS_ALIASES", "").strip().lower() not in _OFF


def expand(tokens: Iterable[str]) -> set[str]:
    """Return `tokens` plus the alias words implied by any known verb.

    Unknown tokens pass through untouched; the result is a plain set so the
    router's `tokens & scope` intersection keeps working on the expanded form.
    """
    base = {t for t in tokens if t}
    if not aliases_enabled():
        return base
    expanded = set(base)
    for token in base:
        for word in ALIASES.get(token, ()):
            expanded.add(word)
    return expanded


def known_verbs() -> Tuple[str, ...]:
    """The verbs this layer understands — used by tests and diagnostics."""
    return tuple(sorted(ALIASES))
