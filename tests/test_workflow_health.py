"""Workflow-health gate: every GitHub Actions workflow must stay loadable.

Nothing in the repo read these files before this gate — a workflow that is
still *valid* YAML passes every linter and GitHub accepts it at submit
time, yet a single corrupted character in a branch filter (say
``branches: ain]`` instead of ``branches: [main]``) silently voids the
push trigger: no branch ever matches, and CI stops existing for direct
pushes with no error anywhere. This gate makes that class of failure loud:

1. the file parses and is a mapping with a workflow ``name``,
2. it declares at least one trigger (``on`` — which YAML 1.1 loads as the
   boolean ``True`` key, so both spellings are accepted),
3. every branch/tag filter is a list of clean literal-or-glob strings —
   no stray brackets from a corrupted flow sequence, no whitespace
   padding, no empty entries,
4. every job declares non-empty ``steps`` (a job that GitHub would reject
   at submit time must fail here first),
5. the three shipping push-triggered workflows really do target ``main``
   — the actual routing contract of this repo.

Everything is stdlib + PyYAML (already a dev dependency), so it runs on
the phone exactly like in CI.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS = _ROOT / ".github" / "workflows"

# Branch filters must look like a ref name or a glob of one: letters, digits,
# and the punctuation GitHub allows — never a stray flow-sequence bracket.
_CLEAN_REF = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    "-_./*"
)


def _workflow_files() -> list[Path]:
    files = sorted(_WORKFLOWS.glob("*.yml"))
    assert files, "no workflow files found under .github/workflows/"
    return files


def _triggers(doc: dict) -> dict:
    """Return the trigger mapping, tolerating YAML 1.1's ``on`` → True."""
    for key in ("on", True):
        if key in doc:
            triggers = doc[key]
            assert isinstance(triggers, dict), (
                f"trigger section is not a mapping: {triggers!r}"
            )
            return triggers
    return {}


def _assert_clean_ref_list(where: str, value: object) -> None:
    assert isinstance(value, list) and value, (
        f"{where}: branch filter must be a non-empty list, got {value!r}"
    )
    for entry in value:
        assert isinstance(entry, str), f"{where}: non-string entry {entry!r}"
        assert entry == entry.strip(), f"{where}: padded entry {entry!r}"
        assert entry, f"{where}: empty entry in {value!r}"
        assert set(entry) <= _CLEAN_REF, (
            f"{where}: suspicious ref {entry!r} — a broken flow sequence "
            f"(e.g. missing '[') ships exactly like this"
        )


# ────────────────────────── per-file structural rules ──────────────────────────

@pytest.mark.parametrize(
    "path", _workflow_files(), ids=lambda p: p.name
)
def test_workflow_parses_with_name_and_triggers(path: Path) -> None:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict), f"{path.name}: top level is not a mapping"
    name = doc.get("name")
    assert isinstance(name, str) and name.strip(), (
        f"{path.name}: missing or empty workflow name"
    )
    triggers = _triggers(doc)
    assert triggers, f"{path.name}: no triggers declared (never runs)"
    for trigger, spec in triggers.items():
        if isinstance(spec, dict) and "branches" in spec:
            _assert_clean_ref_list(f"{path.name}:on.{trigger}.branches", spec["branches"])
        if isinstance(spec, dict) and "branches-ignore" in spec:
            _assert_clean_ref_list(
                f"{path.name}:on.{trigger}.branches-ignore", spec["branches-ignore"]
            )


@pytest.mark.parametrize(
    "path", _workflow_files(), ids=lambda p: p.name
)
def test_every_job_has_steps(path: Path) -> None:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    jobs = doc.get("jobs") or {}
    assert jobs, f"{path.name}: no jobs"
    for job_name, job in jobs.items():
        assert isinstance(job, dict), f"{path.name}:{job_name}: job is not a mapping"
        steps = job.get("steps")
        uses = job.get("uses")
        assert steps or uses, (
            f"{path.name}:{job_name}: job has neither steps nor uses"
        )
        if steps is not None:
            assert isinstance(steps, list) and steps, (
                f"{path.name}:{job_name}: steps is empty"
            )


# ─────────────────────────── the shipping contract ───────────────────────────

def test_push_triggered_workflows_target_main() -> None:
    """The repo contract: CI/tests/landing deploy fire on pushes to main.

    This is the exact clause ``branches: ain]`` silently voided — if the
    filter is edited again, it must stay a clean list containing ``main``.
    """
    expected = {
        "ci.yml": "CI",
        "test.yml": "Tests",
        "deploy-landing.yml": "Deploy Landing (Static)",
    }
    for filename, title in expected.items():
        path = _WORKFLOWS / filename
        assert path.is_file(), f"{filename} is missing"
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert doc.get("name") == title, (
            f"{filename}: workflow name drifted from {title!r}"
        )
        branches = (_triggers(doc).get("push") or {}).get("branches")
        _assert_clean_ref_list(f"{filename}:on.push.branches", branches)
        assert "main" in branches, (
            f"{filename}: push trigger must include 'main', got {branches!r}"
        )


def test_broken_flow_sequence_never_returns() -> None:
    """Regression pin for the corruption class: ``branches: ain]`` —
    a flow sequence missing its opening bracket reads as a harmless
    scalar and voids the trigger with zero errors. This literal text
    must never appear as a live (non-comment) line in any workflow."""
    for path in _workflow_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert not stripped.startswith("branches: ain"), (
                f"{path.name}:{lineno}: corrupted branch filter detected "
                f"(flow sequence missing its opening bracket)"
            )
