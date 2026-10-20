"""Task decomposition — split one request into per-agent subtasks.

PURE and deterministic: no LLM, no I/O, no clock. Given "write and test a
sum function" it returns two subtasks — ``coder`` ("write a sum function") and
``tester`` ("test a sum function") — so the orchestrator can run more than one
agent for a single request.

The rule is deliberately simple and debuggable:

1. **Split** the request into clauses on connectors (``and``, ``then``, ``;``,
   ``،`` …). A single-clause request stays a single subtask.
2. **Map** each clause to an agent by a verb lexicon (``write``→coder,
   ``test``→tester, ``review``→reviewer …). The clause's own wording wins over
   the legacy single-route decision when a verb is recognised.
3. **Fall back** to the existing keyword router for a clause no verb matched,
   so the natural-language path is never worse than before.
4. **Dedupe** by agent, so "write tests and run tests" is one ``tester`` job.

An unknown agent is never invented — every returned id is either in the
lexicon (which is validated against the registry by the tests) or the router's
own answer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple

from .risk import RiskLevel, classify

# ── clause splitting ────────────────────────────────────────────────────────
# Word connectors must be surrounded by spaces so "sand"/"android" never split.
# Punctuation connectors are matched anywhere. Ordered longest-first where it
# matters ("as well as" before "as").
_CONNECTORS = (
    " as well as ", " and then ", " along with ",
    " and ", " then ", " also ", " plus ",
    ";", "؛", "،", ", ",
)
_LEADING_VERB_RE = re.compile(r"^\W*(?:please\s+)?", re.IGNORECASE)


# ── verb → agent lexicon ────────────────────────────────────────────────────
# Each entry: (agent_id, (verb phrases…)). A phrase matches on a whole-word
# basis so "test" never fires inside "latest". Order is irrelevant: the BEST
# (longest) phrase across all entries wins, and ties keep agent order.
_LEXICON: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("tester", ("test", "tests", "testing", "unit test", "write test",
                "run test", "cover", "coverage")),
    ("reviewer", ("review", "code review")),
    ("documentation", ("document", "documentation", "docs", "docstring",
                       "readme", "comment", "explain")),
    ("refactor", ("refactor", "restructure", "clean up", "cleanup")),
    ("debugger", ("debug", "fix bug", "fix the bug", "diagnose", "traceback")),
    ("coder", ("write", "implement", "add", "create", "build", "code",
               "function", "endpoint", "feature", "class", "module")),
    ("planner", ("plan", "breakdown", "break down", "decompose", "roadmap")),
    ("architect", ("architecture", "design system", "system design")),
    ("designer", ("ui", "ux", "design", "mockup", "layout")),
    ("security_auditor", ("security", "audit", "vulnerabilit", "pentest")),
    ("performance", ("performance", "optimize", "optimise", "profile",
                     "speed up", "benchmark")),
    ("devops", ("deploy", "ci", "pipeline", "docker", "release")),
    ("researcher", ("research", "search", "find out", "fact check",
                    "investigate")),
    ("analyst", ("analyze", "analyse", "analysis", "data", "patterns")),
    ("estimator", ("estimate", "effort", "cost", "how long")),
    ("monitor", ("monitor", "metrics", "alert", "watch")),
    ("reporter", ("report", "summarize", "summarise", "summary")),
    ("recovery", ("rollback", "restore", "recover")),
    ("compliance", ("compliance", "policy", "regulatory")),
)

_WORD_RE = re.compile(r"[a-z][a-z0-9]+")

# Human-readable titles for the plan, when the agent is in the lexicon.
_TITLES = {
    "coder": "write", "tester": "test", "reviewer": "review",
    "documentation": "document", "refactor": "refactor", "debugger": "debug",
    "planner": "plan", "architect": "design", "designer": "design",
    "security_auditor": "audit", "performance": "optimize", "devops": "deploy",
    "researcher": "research", "analyst": "analyse", "estimator": "estimate",
    "monitor": "monitor", "reporter": "report", "recovery": "recover",
    "compliance": "check",
}


@dataclass(frozen=True)
class SubTask:
    """One agent-sized piece of a request."""

    agent: str
    request: str
    risk: RiskLevel

    def to_dict(self) -> dict:
        return {"agent": self.agent, "request": self.request,
                "risk": self.risk.value}


def split_clauses(request: str) -> List[str]:
    """Split a request on connectors, preserving the clause text.

    Pure: an empty/blank request yields ``[]``. Single-clause input yields a
    one-element list (with surrounding whitespace stripped).
    """
    if not isinstance(request, str) or not request.strip():
        return []
    text = request.strip()
    for conn in _CONNECTORS:
        text = text.replace(conn, "\x00")
    clauses = [c.strip(" \t\x00") for c in text.split("\x00")]
    return [c for c in clauses if c]


def _match_agent(clause: str) -> Optional[str]:
    """Best (longest phrase) lexicon match for a clause, or ``None``."""
    words = set(_WORD_RE.findall(clause.lower()))
    best: Optional[Tuple[int, int, str]] = None  # (-len, rank, agent)
    for rank, (agent, phrases) in enumerate(_LEXICON):
        for phrase in phrases:
            pwords = _WORD_RE.findall(phrase)
            if pwords and all(w in words for w in pwords):
                key = (-len(pwords), rank, agent)
                if best is None or key < best:
                    best = key
    return best[2] if best else None


def decompose(
    request: str,
    *,
    router: Optional[Any] = None,
    registry: Optional[Any] = None,
    genome: Optional[Any] = None,
) -> List[SubTask]:
    """Break ``request`` into subtasks (one per participating agent).

    ``router`` is the existing :func:`~src.orchestrator.router.route`; when not
    given it is imported lazily. A clause the lexicon cannot classify is routed
    with the legacy keyword router, so a single-clause request behaves exactly
    like the pre-decomposition path.
    """
    clauses = split_clauses(request)
    if not clauses:
        return []
    route_clause = router
    if route_clause is None:  # lazy import keeps the module import-light
        from .router import route as _route

        route_clause = _route

    chosen: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for clause in clauses:
        agent = _match_agent(clause)
        if agent is None:
            try:
                agent = route_clause(clause, registry=registry, genome=genome)
            except Exception:
                agent = "coder"
        if agent in seen:
            continue
        seen.add(agent)
        chosen.append((agent, clause))

    return [
        SubTask(agent=agent, request=clause, risk=classify(clause))
        for agent, clause in chosen
    ]


def merge_outputs(subtasks: Sequence[SubTask],
                  results: Sequence[dict]) -> str:
    """Join per-subtask outputs into ONE reviewable text block.

    Kept trivial on purpose (the v1.24.0 choice): a headed section per subtask
    in subtask order. Missing/failed outputs are stated honestly rather than
    omitted, so the merged block never hides a gap.
    """
    parts: List[str] = []
    for i, sub in enumerate(subtasks):
        out = ""
        if i < len(results):
            out = str((results[i] or {}).get("output") or "").strip()
        title = _TITLES.get(sub.agent, sub.agent)
        body = out or "_(no output)_"
        parts.append(f"### {title} — {sub.agent}\n{body}")
    return "\n\n".join(parts)
