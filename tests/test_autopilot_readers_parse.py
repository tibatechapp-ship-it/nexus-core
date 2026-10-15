"""Tests for the autopilot readers' pure helpers (Slice 2).

Every function under test is an offline string -> value transform, so this file
needs no network, no clock and no fixtures.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.novamind.autopilot.readers import (
    KINDS,
    PRIORITIES,
    classify_kind,
    classify_priority,
    extract_areas,
    extract_criteria,
    extract_references,
    fingerprint,
    kind_rank,
    needs_more_info,
    normalize_title,
    priority_rank,
)
from src.novamind.autopilot.readers.task import Task
from src.novamind.autopilot.readers.classify import word_count


# ── title normalisation & fingerprint ────────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Fix Login Timeout", "fix login timeout"),
        ("  Add   dark-mode! ", "add dark mode"),
        ("Café / déjà vu", "caf d j vu"),
        ("", ""),
    ],
)
def test_normalize_title(raw: str, expected: str) -> None:
    assert normalize_title(raw) == expected


def test_fingerprint_is_stable_and_content_based() -> None:
    a = fingerprint("Fix login timeout", "bug")
    b = fingerprint("fix LOGIN timeout!", "bug")  # same content, different case/punct
    assert a == b
    assert len(a) == 16


def test_fingerprint_varies_with_kind() -> None:
    assert fingerprint("Add dark mode", "feature") != fingerprint("Add dark mode", "bug")


# ── rankings ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(("value", "index"), list(zip(PRIORITIES, range(len(PRIORITIES)))))
def test_priority_rank_known(value: str, index: int) -> None:
    assert priority_rank(value) == index


def test_priority_rank_unknown_is_last() -> None:
    assert priority_rank("zzz") == len(PRIORITIES) - 1


@pytest.mark.parametrize(("value", "index"), list(zip(KINDS, range(len(KINDS)))))
def test_kind_rank_known(value: str, index: int) -> None:
    assert kind_rank(value) == index


def test_kind_rank_unknown_is_last() -> None:
    assert kind_rank("zzz") == len(KINDS) - 1


# ── kind classification ──────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        (["bug"], "bug"),
        (["type: bug"], "bug"),
        (["kind/bug"], "bug"),
        (["Defect"], "bug"),
        (["enhancement"], "feature"),
        (["documentation"], "docs"),
        (["question"], "question"),
        (["support"], "question"),
        (["chore"], "chore"),
        (["ci"], "chore"),
    ],
)
def test_classify_kind_from_labels(labels: list[str], expected: str) -> None:
    assert classify_kind("whatever", "whatever", labels) == expected


@pytest.mark.parametrize(
    ("title", "body", "expected"),
    [
        ("App crashes on start", "", "bug"),
        ("Please document the API", "", "docs"),
        ("How do I install this?", "", "question"),
        ("Add webhooks support", "", "feature"),
        ("Refactor the router", "", "chore"),
        ("Misc", "nothing notable here", "other"),
    ],
)
def test_classify_kind_falls_back_to_keywords(title: str, body: str, expected: str) -> None:
    assert classify_kind(title, body, []) == expected


def test_classify_kind_labels_win_over_keywords() -> None:
    # title screams "crash" but the label says it is a feature request
    assert classify_kind("crash on start", "please add a mode", ["enhancement"]) == "feature"


# ── priority classification ──────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        (["p0"], "p0"),
        (["critical"], "p0"),
        (["blocker"], "p0"),
        (["priority:urgent"], "p0"),
        (["p1"], "p1"),
        (["priority:high"], "p1"),
        (["major"], "p1"),
        (["p2"], "p2"),
        (["medium"], "p2"),
        (["priority:2"], "p2"),
        (["p3"], "p3"),
        (["low"], "p3"),
        (["priority:0"], "p0"),
        ([], "none"),
        (["bug"], "none"),
    ],
)
def test_classify_priority(labels: list[str], expected: str) -> None:
    assert classify_priority(labels) == expected


# ── areas ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "label",
    ["area:auth", "area-auth", "area auth", "component:ui", "module-api", "scope db", "pkg/core"],
)
def test_extract_areas_from_labels(label: str) -> None:
    assert extract_areas("t", "b", [label])


def test_extract_areas_values_are_stripped() -> None:
    assert extract_areas("t", "b", ["area: auth"]) == ("auth",)


def test_extract_areas_from_paths() -> None:
    areas = extract_areas("touch src/core/router.py", "also web/app.js please")
    assert "src/core/router.py" in areas
    assert "web/app.js" in areas


def test_extract_areas_dedupes_preserving_order() -> None:
    areas = extract_areas("t", "src/a.py and src/a.py", ["area:x", "area:x"])
    assert areas == ("x", "src/a.py")


def test_extract_areas_none() -> None:
    assert extract_areas("just a title", "no paths here", ["bug"]) == ()


# ── acceptance criteria ──────────────────────────────────────────────────────
def test_extract_criteria_checkboxes() -> None:
    body = "Steps:\n- [ ] user can log in\n- [x] session persists\n- plain bullet"
    assert extract_criteria(body) == ("user can log in", "session persists")


def test_extract_criteria_section_fallback() -> None:
    body = "## Acceptance criteria\n- login works\n- logout works\n"
    assert extract_criteria(body) == ("login works", "logout works")


def test_extract_criteria_definition_of_done_heading() -> None:
    body = "### Definition of Done\n* tests pass\n"
    assert extract_criteria(body) == ("tests pass",)


def test_extract_criteria_checkboxes_win_over_section() -> None:
    body = "## Acceptance criteria\n- section bullet\n- [ ] checkbox wins\n"
    assert extract_criteria(body) == ("checkbox wins",)


def test_extract_criteria_section_ignores_non_bullets() -> None:
    body = "## Acceptance criteria\na plain sentence\n- real bullet\n"
    assert extract_criteria(body) == ("real bullet",)


def test_extract_criteria_empty() -> None:
    assert extract_criteria("just prose, no list") == ()


# ── references ───────────────────────────────────────────────────────────────
def test_extract_references_urls_and_issue_refs() -> None:
    body = "See https://example.com/a and #12, also https://example.com/a"
    assert extract_references("t", body) == ("https://example.com/a", "#12")


def test_extract_references_empty() -> None:
    assert extract_references("no links", "nothing") == ()


# ── word count & triage ──────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("text", "expected"),
    [("one two three", 3), ("", 0), ("v1.2.3 released", 4), ("a-b c", 3)],
)
def test_word_count(text: str, expected: int) -> None:
    assert word_count(text) == expected


def test_needs_more_info_short_body_no_criteria() -> None:
    assert needs_more_info(body="it broke", criteria=(), labels=[]) is True


def test_needs_more_info_satisfied_by_criteria() -> None:
    assert needs_more_info(body="x", criteria=["works"], labels=[], min_words=8) is False


def test_needs_more_info_satisfied_by_long_body() -> None:
    body = " ".join(f"w{i}" for i in range(20))
    assert needs_more_info(body=body, criteria=(), labels=[]) is False


def test_needs_more_info_forced_by_label() -> None:
    long_body = " ".join(f"w{i}" for i in range(50))
    assert needs_more_info(body=long_body, criteria=["x"], labels=["needs-info"]) is True


def test_needs_more_info_respects_min_words() -> None:
    body = "one two three four five six"  # 6 words
    assert needs_more_info(body=body, criteria=(), labels=[], min_words=5) is False
    assert needs_more_info(body=body, criteria=(), labels=[], min_words=7) is True


# ── Task value object ────────────────────────────────────────────────────────
def _task(**overrides: object) -> Task:
    base: dict[str, object] = {
        "platform": "github",
        "number": 1,
        "title": "Fix login",
        "body": "b",
        "url": "u",
        "author": "alice",
        "state": "open",
        "labels": ("bug",),
        "kind": "bug",
        "priority": "p1",
        "areas": ("auth",),
        "criteria": ("works",),
        "references": ("#2",),
        "needs_info": False,
        "fingerprint": "abc",
    }
    base.update(overrides)
    return Task(**base)  # type: ignore[arg-type]


def test_task_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        _task().title = "x"  # type: ignore[misc]


def test_task_ready_is_inverse_of_needs_info() -> None:
    assert _task(needs_info=False).ready is True
    assert _task(needs_info=True).ready is False


def test_task_to_dict_is_json_shaped() -> None:
    data = _task().to_dict()
    assert data["labels"] == ["bug"]
    assert data["areas"] == ["auth"]
    assert data["criteria"] == ["works"]
    assert data["references"] == ["#2"]
    assert data["ready"] is True
    assert data["fingerprint"] == "abc"


def test_task_summary() -> None:
    assert _task().summary() == "[p1 bug] Fix login (#1)"
