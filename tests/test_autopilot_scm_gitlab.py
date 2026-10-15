"""Tests for the GitLab SCM adapter (Slice 1 — read-only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.novamind.autopilot.scm import (
    AuthError,
    GitLabSCM,
    RateLimitError,
    RecordingTransport,
    Response,
    TransientError,
)

FIXTURES = Path(__file__).parent / "fixtures" / "scm"


def _resp(status: int, payload: object = None, headers: dict[str, str] | None = None) -> Response:
    body = b"" if payload is None else json.dumps(payload).encode()
    return Response(status=status, headers=headers or {}, body=body)


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def _client(transport: RecordingTransport, token: str = "tok") -> GitLabSCM:
    return GitLabSCM(token, project="g/n", transport=transport)


def test_whoami_and_token_header() -> None:
    transport = RecordingTransport([_resp(200, {"username": "vixonapp"})])
    assert GitLabSCM("tok", transport=transport).whoami() == "vixonapp"
    assert transport.requests[0].headers["PRIVATE-TOKEN"] == "tok"
    assert transport.requests[0].url.endswith("/api/v4/user")


def test_list_issues_maps_fields_and_normalizes_state() -> None:
    transport = RecordingTransport([_resp(200, _load("gitlab_issues.json"))])
    issues = _client(transport).list_issues()
    assert [i.number for i in issues] == [1, 2]
    first = issues[0]
    assert first.platform == "gitlab"
    assert first.id == 111
    assert first.title == "Fix login timeout"
    assert first.body == "Users are logged out after 60s."
    assert first.state == "open"  # GitLab "opened" normalised
    assert first.labels == ("bug", "p1")
    assert first.author == "alice"
    assert "state=opened" in transport.requests[0].url


def test_list_issues_sends_labels() -> None:
    transport = RecordingTransport([_resp(200, [])])
    _client(transport).list_issues(labels=("bug",), state="closed", limit=5)
    url = transport.requests[0].url
    assert "state=closed" in url
    assert "labels=bug" in url


def test_project_path_is_url_encoded() -> None:
    transport = RecordingTransport([_resp(200, [])])
    GitLabSCM("tok", project="group/proj", transport=transport).list_issues()
    assert "/projects/group%2Fproj/issues" in transport.requests[0].url


def test_numeric_project_id_is_not_encoded() -> None:
    transport = RecordingTransport([_resp(200, [])])
    GitLabSCM("tok", project="1234", transport=transport).list_issues()
    assert "/projects/1234/issues" in transport.requests[0].url


def test_get_issue() -> None:
    transport = RecordingTransport([_resp(200, _load("gitlab_issue.json"))])
    issue = _client(transport).get_issue(1)
    assert issue.number == 1
    assert issue.body.startswith("Users are logged out")
    assert transport.requests[0].url.endswith("/projects/g%2Fn/issues/1")


def test_list_issues_paginates_via_next_page_header() -> None:
    transport = RecordingTransport(
        [
            _resp(200, _load("gitlab_issues.json"), {"X-Next-Page": "2"}),  # type: ignore[arg-type]
            _resp(
                200,
                [
                    {
                        "id": 555,
                        "iid": 3,
                        "title": "third",
                        "description": "",
                        "state": "opened",
                        "labels": [],
                        "author": {"username": "dan"},
                        "web_url": "u",
                    }
                ],
            ),
        ]
    )
    issues = _client(transport).list_issues(limit=3)
    assert [i.number for i in issues] == [1, 2, 3]
    assert "page=2" in transport.requests[1].url


def test_list_issues_stops_on_non_list_body() -> None:
    transport = RecordingTransport([_resp(200, {"message": "not a list"})])
    assert _client(transport).list_issues() == []


def test_get_change_maps_merge_request() -> None:
    payload = _load("gitlab_mrs.json")[0]  # type: ignore[index]
    transport = RecordingTransport([_resp(200, payload)])
    change = _client(transport).get_change(5)
    assert change.number == 5
    assert change.head == "fix/timeout"
    assert change.base == "main"
    assert change.state == "open"
    assert transport.requests[0].url.endswith("/projects/g%2Fn/merge_requests/5")


def test_empty_token_omits_private_token() -> None:
    transport = RecordingTransport([_resp(200, {"username": "x"})])
    GitLabSCM("", transport=transport).whoami()
    assert "PRIVATE-TOKEN" not in transport.requests[0].headers


def test_forbidden_without_retry_after_is_auth_error() -> None:
    transport = RecordingTransport([_resp(403, {"message": "forbidden"})])
    with pytest.raises(AuthError):
        _client(transport).list_issues()


def test_rate_limit_exposes_retry_after() -> None:
    transport = RecordingTransport([_resp(429, {}, {"Retry-After": "9"})])
    with pytest.raises(RateLimitError) as info:
        _client(transport).list_issues()
    assert info.value.retry_after == 9.0


def test_non_json_body_raises_transient() -> None:
    transport = RecordingTransport([Response(status=200, headers={}, body=b"\xff\xfe not json")])
    with pytest.raises(TransientError):
        _client(transport).list_issues()
