"""requirements.txt parsing with a byte-exact round-trip (س1).

The fixer rewrites *only* the version spec of affected lines and must
reproduce every other byte of the manifest exactly — comments, blank lines,
option lines, markers and whitespace are all preserved. Names are normalized
per PEP 503 so advisories match regardless of how the line was written.

Version comparison is a documented PEP 440 subset (dotted numeric release +
the common suffix families dev/alpha/beta/rc/post) — enough for the planner's
"minimal safe bump" decision, declared as a subset rather than pretending
full PEP 440 compliance.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "RequirementLine",
    "compare_versions",
    "normalize_name",
    "parse_requirements",
]

#: PEP 503 name normalization: lowercase, runs of ``-_.`` collapse to ``-``.
_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)$")
#: A PEP 508 direct-URL requirement (``pkg @ https://…``) — never auto-fixed.
_DIRECT_URL_RE = re.compile(r"^\S+\s*@\s*\S+")
#: Legacy VCS line (``git+https://…``) — also never auto-fixed.
_VCS_HINT_RE = re.compile(r"^[^\s]*://")
#: Suffix families and their ordering weight (lower sorts first).
_SUFFIX_WEIGHTS: dict[str, int] = {
    "dev": 0,
    "a": 1, "alpha": 1,
    "b": 2, "beta": 2,
    "c": 3, "pre": 3, "preview": 3, "rc": 3,
    "": 4,
    "post": 5, "r": 5, "rev": 5,
}
_SUFFIX_RE = re.compile(r"^(dev|a|alpha|b|beta|c|pre|preview|rc|post|rev|r)\.?\d*$")
#: A spec must be operator+version pairs (comma separated) — internal
#: whitespace allowed only between an operator and its version. Anything
#: else (plain words, ``--hash=…`` tails) marks the line unparseable so the
#: planner refuses it instead of guessing.
_SPEC_STRICT_RE = re.compile(
    r"^\s*(?:===|==|!=|<=|>=|~=|<|>)\s*[0-9A-Za-z.*+!_,]+"
    r"(?:\s*,\s*(?:===|==|!=|<=|>=|~=|<|>)\s*[0-9A-Za-z.*+!_,]+)*\s*$"
)


@dataclass(frozen=True)
class RequirementLine:
    """One physical line of a requirements manifest.

    ``head``/``spec``/``tail`` reconstruct the line byte-exactly:
    ``head + spec + tail == raw``.  Only ``spec`` is ever rewritten.
    Non-requirement lines (comments, blanks, ``-r`` options) and direct-URL
    lines keep ``is_requirement=False`` so the planner never touches them.
    """

    index: int
    raw: str
    name: str
    display_name: str
    spec: str
    head: str
    tail: str
    is_requirement: bool
    direct_url: bool = False
    parse_error: str = ""


def normalize_name(name: str) -> str:
    """PEP 503: lowercase; runs of ``-``/``_``/``.`` collapse to a single ``-``."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _split_comment(line: str) -> tuple[str, str]:
    """Split a pip-style comment: ``#`` at line start or after whitespace."""
    for i, ch in enumerate(line):
        if ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i], line[i:]
    return line, ""


def _split_version(version: str) -> tuple[tuple[int, ...], int]:
    """Split ``1.9.0rc1`` → ((1, 9, 0), 3): release tuple + suffix weight.

    The release part is matched with a single flat ``[0-9.]+`` group —
    deliberately free of nested quantifiers (the repo's adversarial ReDoS
    gate scans sources for that shape textually, and a flat scan is also
    linear-time by construction).
    """
    text = version.strip().lstrip("v")
    m = re.match(r"^([0-9.]+)(.*)$", text)
    if m is None or not m.group(1).rstrip("."):
        return (0,), 4
    release = tuple(int(part) for part in m.group(1).rstrip(".").split(".") if part)
    rest = m.group(2).lstrip(".-_")
    sm = _SUFFIX_RE.match(rest)
    weight = _SUFFIX_WEIGHTS[sm.group(1)] if sm else _SUFFIX_WEIGHTS[""]
    return release, weight


def compare_versions(a: str, b: str) -> int:
    """Compare two version strings (documented PEP 440 subset).

    Returns -1/0/+1. Release segments compare numerically and are
    zero-padded (``1.0 == 1.0.0``); suffix order is
    dev < alpha < beta < rc < release < post. Unparseable input sorts
    lowest rather than raising — the planner must not crash on odd pins.
    """
    ra, wa = _split_version(a)
    rb, wb = _split_version(b)
    width = max(len(ra), len(rb))
    ra = ra + (0,) * (width - len(ra))
    rb = rb + (0,) * (width - len(rb))
    if ra != rb:
        return -1 if ra < rb else 1
    return (wa > wb) - (wa < wb)


def parse_requirements(text: str) -> list[RequirementLine]:
    """Parse a requirements manifest into per-line records.

    Every line gets a record (so ``serialize`` can reproduce the file
    exactly); only editable requirement lines carry a parsed name/spec.
    """
    out: list[RequirementLine] = []
    for idx, raw in enumerate(text.splitlines()):
        out.append(_parse_line(idx, raw))
    return out


def _parse_line(index: int, raw: str) -> RequirementLine:
    stripped = raw.strip()
    if not stripped:
        return RequirementLine(index, raw, "", "", "", "", "", False)
    if stripped.startswith("#"):
        return RequirementLine(index, raw, "", "", "", "", "", False)
    if stripped.startswith("-"):
        # pip option (-r, --index-url, …) — out of the fixer's reach.
        return RequirementLine(index, raw, "", "", "", "", "", False)

    code, comment = _split_comment(raw)
    code_s = code.strip()
    if _DIRECT_URL_RE.match(code_s) or _VCS_HINT_RE.match(code_s):
        # PEP 508 direct reference or legacy VCS URL — recorded but never
        # rewritten (the egg/package name is not reliably extractable; the
        # planner skips direct_url lines by contract).
        name = code_s.split("@", 1)[0].strip() if "@" in code_s else ""
        return RequirementLine(
            index, raw, normalize_name(name) if name else "", name, "", "", "",
            True, direct_url=True,
        )

    marker = ""
    semi = code.find(";")
    if semi != -1:
        marker = code[semi:]
        code_left = code[:semi]
    else:
        code_left = code

    lead = len(code_left) - len(code_left.lstrip())
    m = _NAME_RE.match(code_left.lstrip())
    if m is None:
        return RequirementLine(
            index, raw, "", "", "", "", "", False,
            parse_error="unparseable requirement",
        )
    display = m.group(1)
    rest = m.group(3)
    spec = rest.strip()
    if spec and not _SPEC_STRICT_RE.match(spec):
        return RequirementLine(
            index, raw, normalize_name(display), display, "", "", "", False,
            parse_error=f"unsupported spec {spec!r}",
        )
    # Byte-exact invariant: head + spec + tail == raw. head spans up to the
    # spec's first char; tail spans from the spec's end through the marker
    # and the comment — so a rewrite can never drop the environment marker.
    if spec:
        spec_start = lead + m.start(3) + (len(rest) - len(rest.lstrip()))
        head = code_left[:spec_start]
        tail = code_left[spec_start + len(spec):] + marker + comment
    else:
        head = code_left
        tail = marker + comment
    return RequirementLine(
        index, raw, normalize_name(display), display, spec, head, tail, True,
    )


def replace_spec(line: RequirementLine, new_spec: str) -> str:
    """Rewrite only the version spec of one parsed line."""
    if not line.is_requirement or line.direct_url or line.parse_error:
        return line.raw
    return f"{line.head}{new_spec}{line.tail}"
