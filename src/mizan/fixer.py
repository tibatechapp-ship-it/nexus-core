"""Deterministic fix planner — the س1 answer to "no automated remediation".

Given manifest lines and advisories the planner computes the *minimal safe
bump* per affected package: the highest declared fixed version, pinned as
``==<fixed>``. It never invents a target from a heuristic beyond that, skips
what it cannot decide (no fixed version declared, direct URLs) with an
explicit reason, and treats range specs conservatively (an unpinned or
ranged requirement is assumed vulnerable — declared in MIZAN_ROADMAP.md س1).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .advisories import Advisory
from .manifest import RequirementLine, replace_spec

__all__ = ["FixPlan", "PlanResult", "apply_plans", "plan_fixes", "render_diff"]

_PIN_RE = re.compile(r"^==\s*(.+)$")


@dataclass(frozen=True)
class FixPlan:
    """One planned rewrite of one manifest line."""

    package: str            # normalized name
    display_name: str
    line_index: int
    current_spec: str
    target_spec: str        # always "==<fixed>"
    advisory_ids: tuple[str, ...]
    severity: str           # highest severity among the merged advisories
    reason: str             # human-readable, goes into the fix PR body


@dataclass(frozen=True)
class SkipNote:
    """An advisory we deliberately did not act on — honesty over silence."""

    package: str
    line_index: int
    reason: str


@dataclass(frozen=True)
class PlanResult:
    plans: list[FixPlan] = field(default_factory=list)
    skipped: list[SkipNote] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.plans)


def plan_fixes(
    reqs: list[RequirementLine],
    advisories: list[Advisory],
) -> PlanResult:
    """Match advisories to manifest lines and plan minimal safe bumps."""
    by_name: dict[str, list[Advisory]] = {}
    for adv in advisories:
        by_name.setdefault(adv.name, []).append(adv)

    plans: list[FixPlan] = []
    skipped: list[SkipNote] = []
    for line in reqs:
        if not line.is_requirement or line.direct_url or line.parse_error:
            continue
        advs = by_name.get(line.name)
        if not advs:
            continue
        fixed = {a.fixed for a in advs if a.fixed}
        if not fixed:
            skipped.append(SkipNote(
                line.name, line.index,
                "no fixed version declared upstream — refusing to guess",
            ))
            continue
        target = _max_version(fixed)
        if _pin_is_at_least(line.spec, target):
            skipped.append(SkipNote(
                line.name, line.index,
                f"already pinned at/above the fix ({line.spec} vs =={target})",
            ))
            continue
        ids = tuple(dict.fromkeys(
            i for a in sorted(advs, key=lambda a: -a.severity_rank) for i in a.ids
        ))
        top = max(advs, key=lambda a: a.severity_rank).severity.upper()
        plans.append(FixPlan(
            package=line.name,
            display_name=line.display_name,
            line_index=line.index,
            current_spec=line.spec or "(any version)",
            target_spec=f"=={target}",
            advisory_ids=ids,
            severity=top,
            reason=(
                f"{len(advs)} advisory(ies) affect '{line.display_name}' "
                f"({line.spec or 'unpinned'}); minimal safe bump to {target}"
            ),
        ))
    plans.sort(key=lambda p: p.line_index)
    skipped.sort(key=lambda s: s.line_index)
    return PlanResult(plans=plans, skipped=skipped)


def _max_version(candidates: set[str]) -> str:
    return max(candidates, key=lambda v: (_version_sort_key(v)))


def _version_sort_key(version: str) -> tuple[int, ...]:
    from .manifest import _split_version  # local import: reuse release tuple

    return _split_version(version)[0]


def _pin_is_at_least(spec: str, target: str) -> bool:
    """True only for exact ``==X`` pins already ≥ target.

    Ranged or unpinned specs are *not* proven safe → the planner treats
    them as vulnerable (conservative, declared in the roadmap).
    """
    from .manifest import compare_versions  # local import: avoid cycle noise

    m = _PIN_RE.match(spec.strip())
    if m is None:
        return False
    return compare_versions(m.group(1).strip(), target) >= 0


def apply_plans(
    text: str,
    reqs: list[RequirementLine],
    plans: list[FixPlan],
) -> str:
    """Rewrite the manifest applying the plans; everything else is untouched.

    Raises ValueError on an empty plan list — calling apply with nothing to
    do is a caller bug we refuse rather than silently no-op (mirrors the
    v1.58.0 ض6 semantics: no invisible writes).
    """
    if not plans:
        raise ValueError("apply_plans: no plans — refusing a no-op write")
    by_index = {p.line_index: p.target_spec for p in plans}
    lines = text.splitlines()
    out: list[str] = []
    for i, ln in enumerate(lines):
        line = reqs[i] if i < len(reqs) else None
        if line is not None and i in by_index:
            out.append(replace_spec(line, by_index[i]))
        else:
            out.append(ln)
    trailing = "\n" if text.endswith("\n") else ""
    return "\n".join(out) + trailing


def render_diff(original: str, updated: str, label: str = "requirements.txt") -> str:
    """Unified diff of the planned change (empty string when identical)."""
    import difflib

    diff = difflib.unified_diff(
        original.splitlines(), updated.splitlines(),
        fromfile=f"a/{label}", tofile=f"b/{label}", lineterm="",
    )
    return "\n".join(diff)
