"""Contract tests: GitHub and GitLab adapters must be interchangeable.

These assert the *Liskov* property the whole autopilot depends on — the same
worker code, fed identical provider payloads, must see identical neutral value
objects — and that Slice 1 exposes no write surface at all.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.novamind.autopilot.scm import (
    GitHubSCM,
    GitLabSCM,
    RecordingTransport,
    Response,
    SCM,
    SCMWriter,
)

FIXTURES = Path(__file__).parent / "fixtures" / "scm"


def _resp(payload: object) -> Response:
    return Response(status=200, headers={}, body=json.dumps(payload).encode())


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def _github(name: str) -> GitHubSCM:
    return GitHubSCM("t", repo="o/n", transport=RecordingTransport([_resp(_load(name))]))


def _gitlab(name: str) -> GitLabSCM:
    return GitLabSCM("t", project="g/n", transport=RecordingTransport([_resp(_load(name))]))


def test_both_adapters_satisfy_the_scm_protocol() -> None:
    assert isinstance(GitHubSCM("t", repo="o/n"), SCM)
    assert isinstance(GitLabSCM("t", project="g/n"), SCM)


def test_neither_adapter_can_write() -> None:
    # Slice 1 is read-only: the write protocol must be structurally absent.
    assert not isinstance(GitHubSCM("t", repo="o/n"), SCMWriter)
    assert not isinstance(GitLabSCM("t", project="g/n"), SCMWriter)


def test_issues_are_neutral_across_platforms() -> None:
    github_issues = _github("github_issues.json").list_issues()
    gitlab_issues = _gitlab("gitlab_issues.json").list_issues()
    assert len(github_issues) == len(gitlab_issues) == 2  # GitHub filters its PR out
    for gh, gl in zip(github_issues, gitlab_issues):
        assert (gh.id, gh.number, gh.title, gh.body, gh.state, gh.labels, gh.author) == (
            gl.id,
            gl.number,
            gl.title,
            gl.body,
            gl.state,
            gl.labels,
            gl.author,
        )
    assert github_issues[0].platform == "github"
    assert gitlab_issues[0].platform == "gitlab"


def test_changes_are_neutral_across_platforms() -> None:
    gh_change = _github("github_pulls.json").list_changes()[0]
    gl_change = _gitlab("gitlab_mrs.json").list_changes()[0]
    assert (
        gh_change.id,
        gh_change.number,
        gh_change.title,
        gh_change.body,
        gh_change.state,
        gh_change.head,
        gh_change.base,
        gh_change.author,
    ) == (
        gl_change.id,
        gl_change.number,
        gl_change.title,
        gl_change.body,
        gl_change.state,
        gl_change.head,
        gl_change.base,
        gl_change.author,
    )


def test_platform_tags_differ() -> None:
    assert _github("github_issues.json").list_issues()[0].platform == "github"
    assert _gitlab("gitlab_issues.json").list_issues()[0].platform == "gitlab"
