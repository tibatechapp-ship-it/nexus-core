"""Auditable repair plan — the schema every engine edit must declare first.

مخطط الإصلاح المعلن (مهمة M2.3): لا تعديل ملف يمر قبل RepairPlan صالح.
التحقق آلي، والخطة تُخزَّن وتُبَث كـ JSON قابل للتدقيق.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

ACTIONS = ("edit", "create", "delete")
RISK_LEVELS = ("low", "medium", "high")


@dataclass
class Step:
    """One auditable file mutation, declared before it is ever executed.

    ض6 (v1.58.0): ``edit`` now carries an explicit ``find`` block — the unique
    text to replace — instead of relying on an append. ``create``/``delete``
    leave it empty.
    """

    file: str            # target file, repo-relative
    action: str          # edit | create | delete
    reason: str          # why this change, human-readable
    patch_hint: str = ""  # model hint for the edit content (required for edit/create)
    risk: str = "low"    # low | medium | high
    find: str = ""       # unique block an 'edit' replaces (required for edit)


@dataclass
class RepairPlan:
    """A complete, reviewable unit of work: goal, defects, steps, tests."""

    goal: str
    defects: list = field(default_factory=list)
    steps: list = field(default_factory=list)
    tests_to_run: list = field(default_factory=list)
    rollback: str = "git checkout -- ."

    def to_json(self) -> dict:
        """Round-trippable JSON form (plan_from_json is the inverse)."""
        return asdict(self)


def plan_from_json(data: dict) -> RepairPlan:
    """Build a RepairPlan from (model-produced) JSON, tolerating bad shapes."""
    steps = []
    for raw in data.get("steps") or []:
        if not isinstance(raw, dict):
            continue
        steps.append(
            Step(
                file=str(raw.get("file", "")),
                action=str(raw.get("action", "")),
                reason=str(raw.get("reason", "")),
                patch_hint=str(raw.get("patch_hint", "")),
                risk=str(raw.get("risk", "low")),
                find=str(raw.get("find", "")),
            )
        )
    raw_defects = data.get("defects")
    raw_tests = data.get("tests_to_run")
    return RepairPlan(
        goal=str(data.get("goal", "")),
        defects=[str(d) for d in raw_defects] if isinstance(raw_defects, list) else [],
        steps=steps,
        tests_to_run=[str(t) for t in raw_tests] if isinstance(raw_tests, list) else [],
        rollback=str(data.get("rollback", "git checkout -- .")),
    )


def validate(plan: RepairPlan) -> list:
    """Return the list of validation errors; empty list means the plan may run."""
    errors: list = []
    if not plan.goal:
        errors.append("missing goal")
    if not plan.steps:
        errors.append("plan has no steps")
    if not plan.tests_to_run:
        errors.append("plan declares no tests")
    for s in plan.steps:
        if s.action not in ACTIONS:
            errors.append(f"bad action in {s.file}: {s.action!r}")
        if s.risk not in RISK_LEVELS:
            errors.append(f"bad risk level in {s.file}: {s.risk!r}")
        if not s.file or s.file.startswith("/") or ".." in s.file.split("/"):
            errors.append(f"unsafe path in plan: {s.file!r}")
        if s.action in ("edit", "create") and not s.patch_hint:
            errors.append(f"missing patch_hint in {s.file}")
        if s.action == "edit" and not s.find:
            errors.append(f"edit requires a unique 'find' block in {s.file}")
        if s.action != "create" and not s.reason:
            errors.append(f"missing reason in {s.file}")
    return errors
