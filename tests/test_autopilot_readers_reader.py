"""Tests for the autopilot issue reader (Slice 2).

The reader is exercised through a tiny in-memory SCM (no network) and through
the real GitHub/GitLab adapters fed the Slice 1 fixtures, proving the same
worker sees identical tasks on both platforms.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.novamind.autopilot.readers import IssueReader, dedupe, rank, select
from src.novamind.autopilot.readers.task import Task
from src.novamind.autopilot.scm import (
    GitHubSCM,
    GitLabSCM,
    Issue,
    NotFoundError,
    RecordingTransport,
    Response,
)

FIXTURES = Path(__file__).parent / "fixtures" / "scm"


# ── test doubles ─────────────────────────────────────────────────────────────
class FakeSCM:
    """A minimal in-memory :class:`SCM` for reader tests."""

    platform = "fake"

    def __init__(self, issues: list[Issue]) -> None:
        self._issues = list(issues)
        self.calls: list[tuple[tuple[str, ...], str, int]] = []

    def whoami(self) -> str:
        return "tester"

    def list_issues(
        self, *, labels: tuple[str, ...] = (), state: str = "open", limit: int = 20
    ) -> list[Issue]:
        self.calls.append((labels, state, limit))
        return self._issues[:limit]

    def get_issue(self, number: int) -> Issue:
        for issue in self._issues:
            if issue.number == number:
                return issue
        raise NotFoundError(status=404, message=f"no issue {number}")

    def list_changes(self, *, state: str = "open", limit: int = 20) -> list[object]:
        return []

    def get_change(self, number: int) -> object:  # pragma: no cover - unused here
        raise NotFoundError(status=404, message="none")


def _issue(
    number: int,
    title: str,
    *,
    body: str = "",
    labels: tuple[str, ...] = (),
    platform: str = "github",
) -> Issue:
    return Issue(
        platform=platform,
        id=number,
        number=number,
        title=title,
        body=body,
        state="open",
        labels=labels,
        author="alice",
        url=f"https://example.test/{number}",
    )


def _task(priority: str, kind: str, title: str, areas: tuple[str, ...] = ()) -> Task:
    return Task(
        platform="fake",
        number=1,
        title=title,
        body="",
        url="u",
        author="a",
        state="open",
        labels=(),
        kind=kind,
        priority=priority,
        areas=areas,
        criteria=(),
        references=(),
        needs_info=False,
        fingerprint=title.lower(),
    )


# ── IssueReader ──────────────────────────────────────────────────────────────
def test_platform_delegates_to_scm() -> None:
    assert IssueReader(FakeSCM([])).platform == "fake"


def test_read_maps_every_issue_in_order_and_passes_filters() -> None:
    scm = FakeSCM([_issue(1, "Fix login timeout", labels=("bug", "p1")), _issue(2, "Add dark mode")])
    reader = IssueReader(scm)
    tasks = reader.read(labels=("bug",), state="closed", limit=5)
    assert [t.number for t in tasks] == [1, 2]
    assert scm.calls == [(("bug",), "closed", 5)]


def test_to_task_classifies_fully() -> None:
    issue = _issue(
        7,
        "Fix auth crash",
        body="Repro in src/core/auth.py\n- [ ] no crash\n- [x] tests added\nSee #12 and https://ex.co",
        labels=("type: bug", "priority:high", "area:auth"),
    )
    task = IssueReader(FakeSCM([])).to_task(issue)
    assert task.kind == "bug"
    assert task.priority == "p1"
    assert task.areas == ("auth", "src/core/auth.py")
    assert task.criteria == ("no crash", "tests added")
    assert task.references == ("https://ex.co", "#12")
    assert task.needs_info is False
    assert task.ready is True


def test_read_one() -> None:
    scm = FakeSCM([_issue(3, "Third")])
    assert IssueReader(scm).read_one(3).number == 3


def test_min_body_words_is_configurable() -> None:
    scm = FakeSCM([_issue(1, "t", body="one two three four five six")])
    assert IssueReader(scm, min_body_words=3).read()[0].needs_info is False
    assert IssueReader(scm, min_body_words=7).read()[0].needs_info is True


# ── pure transforms ──────────────────────────────────────────────────────────
def test_dedupe_keeps_first_occurrence() -> None:
    tasks = [_task("p1", "bug", "Dup"), _task("p1", "bug", "dup"), _task("p2", "bug", "Other")]
    kept = dedupe(tasks)
    assert [t.title for t in kept] == ["Dup", "Other"]


def test_rank_orders_priority_then_kind_then_title() -> None:
    tasks = [
        _task("p2", "feature", "a"),
        _task("p0", "bug", "zebra"),
        _task("p1", "bug", "x"),
        _task("p0", "bug", "apple"),
    ]
    ordered = [t.title for t in rank(tasks)]
    assert ordered == ["apple", "zebra", "x", "a"]


def test_select_by_kind() -> None:
    tasks = [_task("p1", "bug", "b"), _task("p1", "feature", "f")]
    assert [t.title for t in select(tasks, kinds=("bug",))] == ["b"]


def test_select_by_priority_ceiling() -> None:
    tasks = [_task("p0", "bug", "a"), _task("p1", "bug", "b"), _task("p2", "bug", "c")]
    assert [t.title for t in select(tasks, priority_max="p1")] == ["a", "b"]


def test_select_by_areas() -> None:
    tasks = [_task("p1", "bug", "a", areas=("auth",)), _task("p1", "bug", "b", areas=("ui",))]
    assert [t.title for t in select(tasks, areas=("ui",))] == ["b"]


def test_select_can_drop_needs_info() -> None:
    ready = _task("p1", "bug", "a")
    pending = Task(**{**ready.__dict__, "needs_info": True})
    assert [t.title for t in select([ready, pending], include_needs_info=False)] == ["a"]


def test_collect_composes_read_dedupe_select_rank() -> None:
    scm = FakeSCM(
        [
            _issue(1, "Fix login", labels=("bug", "p2")),
            _issue(2, "Fix login", labels=("bug", "p2")),  # duplicate title
            _issue(3, "Add dark mode", labels=("enhancement", "p0")),
        ]
    )
    tasks = IssueReader(scm).collect(kinds=("bug",))
    assert [t.title for t in tasks] == ["Fix login"]  # dup dropped, feature filtered


# ── cross-platform contract (real adapters + fixtures) ───────────────────────
def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def _resp(payload: object) -> Response:
    return Response(status=200, headers={}, body=json.dumps(payload).encode())


def test_reader_yields_identical_tasks_across_platforms() -> None:
    github = IssueReader(
        GitHubSCM("t", repo="o/n", transport=RecordingTransport([_resp(_load("github_issues.json"))]))
    ).read()
    gitlab = IssueReader(
        GitLabSCM("t", project="g/n", transport=RecordingTransport([_resp(_load("gitlab_issues.json"))]))
    ).read()
    assert len(github) == len(gitlab) == 2  # GitHub's PR is filtered by the adapter

    def shape(task: Task) -> tuple[object, ...]:
        return (task.kind, task.priority, task.areas, task.criteria, task.references, task.needs_info, task.fingerprint)

    assert [shape(t) for t in github] == [shape(t) for t in gitlab]
    assert github[0].kind == "bug" and github[0].priority == "p1"
    assert github[1].kind == "feature" and github[1].priority == "none"
