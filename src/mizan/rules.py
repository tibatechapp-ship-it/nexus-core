"""MIZAN rules DSL (س6) — custom rules as reviewed JSON over ``ast``.

The competitive review (MIZAN_ROADMAP.md س6) named the gap: Semgrep lets a
team write its own patterns; MIZAN was read-only over its built-ins. The
declared scope here is deliberately the *easy* 80%: match AST nodes by
class name, optionally pin the dotted name the node must resolve to, and
optionally run a flat regex over the unparsed snippet.

Rule schema (``mizan.rules/1``)::

    {"schema": "mizan.rules/1", "rules": [{
        "id": "MY-001",
        "match": {"node": "Call", "pattern": "eval", "regex": ""},
        "severity": "HIGH",
        "message": "…", "fix-hint": "…"
    }]}

Matching semantics (all declared, no magic):

* ``node`` — an ``ast`` class name from the whitelist (Call/Attribute/
  Name/Subscript/Import/ImportFrom); anything else is a load error, not
  a silent no-op.
* ``pattern`` — dotted name the node resolves to (``Call``→ its func,
  ``Attribute``/``Name``/``Subscript``→ the dotted value, ``Import``→
  the module). Matches equal or *suffix* after a dot (``os.system``
  matches ``os.system`` and ``subprocess.os.system``-style chains).
* ``regex`` — flat (linear-time) regex matched against
  ``ast.unparse(node)`` truncated to 2000 chars; nested quantifiers are
  rejected at load time (the same ReDoS discipline as the repo gate).
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .reachability import iter_py_files

__all__ = [
    "SCHEMA",
    "Rule",
    "RuleFinding",
    "RulesError",
    "builtin_rules",
    "builtin_rules_path",
    "check_path",
    "load_rules",
]

SCHEMA = "mizan.rules/1"

#: Node classes a rule may target — a whitelist keeps the DSL honest.
_ALLOWED_NODES: frozenset[str] = frozenset({
    "Call", "Attribute", "Name", "Subscript", "Import", "ImportFrom",
})

_SEV = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

#: ReDoS gate: reject the nested-quantifier shape the repo's adversarial
#: suite hunts for (a quantified group, e.g. group-plus-quantified) at
#: rule-load time.
_NESTED_QUANT_RE = re.compile(r"\([^)]*[+*]\)[+*]")

#: ``ast.unparse`` cap — a rule regex never sees unbounded source.
_MAX_SNIPPET = 2000


class RulesError(ValueError):
    """A rules file (or one rule) does not conform to the declared schema."""


@dataclass(frozen=True)
class Rule:
    """One compiled rule."""

    id: str
    node: str
    pattern: str
    regex: re.Pattern[str] | None
    severity: str
    message: str
    fix_hint: str


@dataclass(frozen=True)
class RuleFinding:
    """One match of one rule at one location."""

    rule_id: str
    severity: str
    message: str
    fix_hint: str
    path: str
    line: int
    snippet: str


def _compile_regex(expr: str) -> re.Pattern[str] | None:
    """Compile a rule regex, refusing nested-quantifier shapes."""
    if not expr:
        return None
    if _NESTED_QUANT_RE.search(expr):
        raise RulesError(f"rule regex is not flat (ReDoS-gate): {expr!r}")
    try:
        return re.compile(expr)
    except re.error as exc:
        raise RulesError(f"bad rule regex {expr!r}: {exc}") from exc


def _parse_rule(i: int, row: dict[str, object]) -> Rule:
    rid = str(row.get("id", "")).strip()
    if not rid:
        raise RulesError(f"rule #{i}: missing 'id'")
    match = row.get("match")
    if not isinstance(match, dict):
        raise RulesError(f"rule #{i} ({rid}): missing 'match' object")
    node = str(match.get("node", "")).strip()
    if node not in _ALLOWED_NODES:
        raise RulesError(
            f"rule #{i} ({rid}): match.node {node!r} not in the whitelist "
            f"{sorted(_ALLOWED_NODES)}"
        )
    pattern = str(match.get("pattern", "")).strip()
    severity = str(row.get("severity", "MEDIUM")).upper()
    if severity not in _SEV:
        raise RulesError(
            f"rule #{i} ({rid}): severity {severity!r} not in {sorted(_SEV)}"
        )
    message = str(row.get("message", "")).strip()
    if not message:
        raise RulesError(f"rule #{i} ({rid}): missing 'message'")
    return Rule(
        id=rid,
        node=node,
        pattern=pattern,
        regex=_compile_regex(str(match.get("regex", ""))),
        severity=severity,
        message=message,
        fix_hint=str(row.get("fix-hint", "")),
    )


def load_rules(path: Path) -> list[Rule]:
    """Load + validate a rules file (schema ``mizan.rules/1``)."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RulesError(f"cannot read rules file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RulesError(f"{path}: rules file must be a JSON object")
    if str(payload.get("schema", SCHEMA)) != SCHEMA:
        raise RulesError(f"{path}: unsupported schema (want {SCHEMA!r})")
    rows = payload.get("rules")
    if not isinstance(rows, list):
        raise RulesError(f"{path}: missing 'rules' list")
    out: list[Rule] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise RulesError(f"{path}: rule #{i} must be an object")
        out.append(_parse_rule(i, row))
    return out


def builtin_rules_path() -> Path:
    """The shipped reviewed built-ins (migrating bandit picks, dogfooded)."""
    return Path(__file__).with_name("data") / "builtin_rules.json"


def builtin_rules() -> list[Rule]:
    """Load the built-in rules shipped with MIZAN."""
    return load_rules(builtin_rules_path())


def _node_dotted(node: ast.AST) -> str:
    """The dotted name a matchable node resolves to (may be empty)."""
    target: ast.AST
    if isinstance(node, ast.Call):
        target = node.func
    elif isinstance(node, ast.Import):
        return ""
    elif isinstance(node, ast.ImportFrom):
        return node.module or ""
    else:
        target = node
    parts: list[str] = []
    cur: ast.AST = target
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _pattern_hit(rule: Rule, dotted: str, node: ast.AST) -> bool:
    """Does the node match the rule's pattern? (empty pattern = any)"""
    pattern = rule.pattern
    if not pattern:
        return True  # node-type-only rule
    if isinstance(node, ast.Import):
        return any(
            a.name == pattern or a.name.endswith("." + pattern)
            for a in node.names
        )
    return dotted == pattern or dotted.endswith("." + pattern)


def _match_node(rule: Rule, node: ast.AST, path: str) -> RuleFinding | None:
    cls = type(node).__name__
    if cls != rule.node:
        return None
    dotted = _node_dotted(node)
    if not _pattern_hit(rule, dotted, node):
        return None
    try:
        snippet = ast.unparse(node)[:_MAX_SNIPPET]
    except Exception:  # noqa: BLE001 — unparse is best-effort
        snippet = ""
        if rule.regex is not None:
            return None  # cannot evaluate the regex → no match, honestly
    if rule.regex is not None and rule.regex.search(snippet) is None:
        return None
    return RuleFinding(
        rule_id=rule.id,
        severity=rule.severity,
        message=rule.message,
        fix_hint=rule.fix_hint,
        path=path,
        line=getattr(node, "lineno", 0) or 0,
        snippet=snippet,
    )


def check_path(
    root: Path,
    rules: list[Rule],
) -> tuple[list[RuleFinding], int, int]:
    """Run rules over every ``*.py`` file; returns (findings, scanned, unparsed).

    Import nodes never carry a snippet line of their own beyond the match
    (they are one-liners by construction).
    """
    findings: list[RuleFinding] = []
    scanned = 0
    unparsed = 0
    for path in iter_py_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        except (SyntaxError, ValueError, OSError, UnicodeDecodeError):
            unparsed += 1
            continue
        scanned += 1
        rel = str(path.relative_to(root))
        for node in ast.walk(tree):
            for rule in rules:
                hit = _match_node(rule, node, rel)
                if hit is not None:
                    findings.append(hit)
    return findings, scanned, unparsed
