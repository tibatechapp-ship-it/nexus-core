"""Pure parsing and classification for autopilot readers (Slice 2).

Every function here is a deterministic string -> value transform with **no I/O
and no clock**, so the whole reader is exercised offline. The reader
(:mod:`...reader`) is a thin shell that maps an SCM :class:`Issue` through these.

Two rules keep results predictable across providers:

* label tokens are normalised once (:func:`_norm_token`): lower-cased, and any
  ``type:``/``kind/`` style prefix is dropped, so ``Bug``, ``type: bug`` and
  ``kind/bug`` all mean the same thing;
* classification prefers explicit labels over title/body keyword guesses.
"""

from __future__ import annotations

import re
from typing import Iterable

__all__ = [
    "classify_kind",
    "classify_priority",
    "extract_areas",
    "extract_criteria",
    "extract_references",
    "needs_more_info",
    "word_count",
]

# ── label vocabulary ─────────────────────────────────────────────────────────
_KIND_LABELS: tuple[tuple[str, frozenset[str]], ...] = (
    ("bug", frozenset({"bug", "defect", "error", "crash", "regression", "broken"})),
    ("feature", frozenset({"feature", "enhancement", "request", "new"})),
    ("docs", frozenset({"docs", "documentation"})),
    ("question", frozenset({"question", "support", "help", "howto", "how-to"})),
    ("chore", frozenset({"chore", "maintenance", "refactor", "cleanup", "ci", "build", "deps"})),
)

_PRIORITY_LABELS: tuple[tuple[str, frozenset[str]], ...] = (
    ("p0", frozenset({"p0", "critical", "blocker", "urgent", "sev0"})),
    ("p1", frozenset({"p1", "high", "major", "important", "sev1"})),
    ("p2", frozenset({"p2", "medium", "normal", "moderate", "sev2"})),
    ("p3", frozenset({"p3", "low", "minor", "trivial", "sev3"})),
)

_AREA_PREFIXES: tuple[str, ...] = ("area", "component", "module", "scope", "pkg", "package")

# ── keyword fallbacks (used only when labels are silent) ─────────────────────
_KIND_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bug", ("crash", "error", "bug", "broken", "fails", "failure", "exception", "traceback", "regression", "fix")),
    ("docs", ("readme", "docs", "documentation", "document", "typo")),
    ("question", ("how", "why", "what", "question", "?")),
    ("feature", ("add", "support", "request", "feature", "implement", "allow", "enable")),
    ("chore", ("refactor", "cleanup", "bump", "upgrade", "ci", "lint")),
)

# ── regexes ──────────────────────────────────────────────────────────────────
_TOKEN_WS = re.compile(r"\s+")
_CHECKBOX = re.compile(r"^\s*[-*+]\s*\[[ xX]\]\s*(?P<text>.+?)\s*$")
_BULLET = re.compile(r"^\s*[-*+]\s+(?P<text>.+?)\s*$")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*(?P<text>.+?)\s*$")
_URL = re.compile(r"https?://[^\s)>\]]+")
_ISSUE_REF = re.compile(r"(?<![\w])#(\d+)")
_PATH = re.compile(r"(?<![\w./-])(?:[\w.-]+/)+[\w.-]+\.(?:py|js|ts|tsx|jsx|md|json|ya?ml|toml|cfg|ini|txt|html|css|sh)\b")
_WORD = re.compile(r"[A-Za-z0-9_]+")

_CRITERIA_HEADINGS: frozenset[str] = frozenset(
    {"acceptance criteria", "definition of done", "done when", "criteria", "success criteria"}
)


def _norm_token(raw: str) -> str:
    """Normalise one label: lower-case, trim, drop a ``type:``/``type/`` prefix."""
    token = raw.strip().lower()
    for sep in (":", "/"):
        if sep in token:
            head, _, tail = token.partition(sep)
            # "type: bug" -> "bug"; keep plain words that merely contain a slash
            if head in {"type", "kind", "label", "priority", "prio", "sev", "severity"} and tail.strip():
                token = tail.strip()
                break
    return _TOKEN_WS.sub(" ", token).strip()


def word_count(text: str) -> int:
    """Count meaningful word tokens in ``text`` (isalnum runs, digits kept)."""
    return len(_WORD.findall(text))


def _label_tokens(labels: Iterable[str]) -> list[str]:
    return [_norm_token(item) for item in labels]


# ── kind ─────────────────────────────────────────────────────────────────────
def classify_kind(title: str, body: str, labels: Iterable[str] = ()) -> str:
    """Return the task kind: bug / feature / docs / question / chore / other.

    Explicit labels win; otherwise keyword hints scan the title then the body.
    """
    tokens = _label_tokens(labels)
    for kind, names in _KIND_LABELS:
        if any(token in names for token in tokens):
            return kind
    haystack = f"{title}\n{body}".lower()
    for kind, hints in _KIND_HINTS:
        if any(hint in haystack for hint in hints):
            return kind
    return "other"


# ── priority ─────────────────────────────────────────────────────────────────
def classify_priority(labels: Iterable[str] = ()) -> str:
    """Return p0/p1/p2/p3/none, derived from labels (``priority:high`` ok)."""
    tokens = _label_tokens(labels)
    for priority, names in _PRIORITY_LABELS:
        if any(token in names for token in tokens):
            return priority
    # bare numeric "priority:1" style already normalised to "1"
    for token in tokens:
        if token in {"0", "1", "2", "3"}:
            return f"p{token}"
    return "none"


# ── areas ────────────────────────────────────────────────────────────────────
def _area_value(token: str) -> str | None:
    """Extract the value of an area-style label (``area:auth`` / ``component-ui``)."""
    for prefix in _AREA_PREFIXES:
        for sep in (":", "-", "/", " "):
            if token.startswith(f"{prefix}{sep}"):
                value = token[len(prefix) + 1 :].strip().lstrip("-/: ")
                return value or None
    return None


def extract_areas(title: str, body: str, labels: Iterable[str] = ()) -> tuple[str, ...]:
    """Return affected areas: from ``area:`` labels and file paths in the text."""
    areas: list[str] = []
    for token in _label_tokens(labels):
        value = _area_value(token)
        if value is not None:
            areas.append(value)
    for path in _PATH.findall(f"{title}\n{body}"):
        areas.append(path)
    return tuple(dict.fromkeys(areas))


# ── acceptance criteria ──────────────────────────────────────────────────────
def extract_criteria(body: str) -> tuple[str, ...]:
    """Extract acceptance criteria.

    Checkbox list items (``- [ ]`` / ``- [x]``) are collected anywhere in the
    body; if none exist, the bullet list under an "acceptance criteria" /
    "definition of done" heading is used instead. Results are de-duplicated
    preserving order.
    """
    criteria: list[str] = []
    section_bullets: list[str] = []
    in_criteria_section = False
    for line in body.splitlines():
        heading = _HEADING.match(line)
        if heading:
            in_criteria_section = heading.group("text").strip().lower() in _CRITERIA_HEADINGS
            continue
        checkbox = _CHECKBOX.match(line)
        if checkbox:
            criteria.append(checkbox.group("text").strip())
            continue
        if in_criteria_section:
            bullet = _BULLET.match(line)
            if bullet:
                section_bullets.append(bullet.group("text").strip())
    if not criteria:
        criteria = section_bullets
    return tuple(dict.fromkeys(item for item in criteria if item))


# ── references ───────────────────────────────────────────────────────────────
def extract_references(title: str, body: str) -> tuple[str, ...]:
    """Return referenced URLs and ``#NNN`` cross-links, de-duplicated in order."""
    text = f"{title}\n{body}"
    refs: list[str] = list(_URL.findall(text))
    refs.extend(f"#{number}" for number in _ISSUE_REF.findall(text))
    return tuple(dict.fromkeys(refs))


# ── triage signal ────────────────────────────────────────────────────────────
_NEEDS_INFO_LABELS: frozenset[str] = frozenset({"needs-info", "needs info", "triage", "incomplete", "question"})


def needs_more_info(
    *,
    body: str,
    criteria: Iterable[str] = (),
    labels: Iterable[str] = (),
    min_words: int = 8,
) -> bool:
    """Decide whether a task lacks the detail to act on.

    True when an explicit triage label is present, or when the task has *no*
    acceptance criteria **and** a body shorter than ``min_words`` meaningful
    words. Deliberately conservative: a listed criterion always counts as
    enough, so the reader never nags about a well-specified issue.
    """
    if any(token in _NEEDS_INFO_LABELS for token in _label_tokens(labels)):
        return True
    return not tuple(criteria) and word_count(body) < min_words
