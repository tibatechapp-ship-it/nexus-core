"""Tests for the GitHub SCM adapter (Slice 1 — read-only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.novamind.autopilot.scm import (
    AuthError,
    GitHubSCM,
    NotFoundError,
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


def _client(transport: RecordingTransport, token: str = "tok") -> GitHubSCM:
    return GitHubSCM(token, repo="o/n", transport=transport)


def test_whoami() -> None:
    transport = RecordingTransport([_resp(200, {"login": "alice"})])
    assert _client(transport).whoami() == "alice"
    assert transport.requests[0].url.endswith("/user")


def test_list_issues_maps_fields_and_filters_pull_requests() -> None:
    transport = RecordingTransport([_resp(200, _load("github_issues.json"))])
    issues = _client(transport).list_issues()
    assert [i.number for i in issues] == [1, 2]  # the PR (#3) is filtered out
    first = issues[0]
    assert first.platform == "github"
    assert first.id == 111
    assert first.title == "Fix login timeout"
    assert first.state == "open"
    assert first.labels == ("bug", "p1")
    assert first.author == "alice"


def test_list_issues_sends_state_and_labels() -> None:
    transport = RecordingTransport([_resp(200, [])])
    _client(transport).list_issues(labels=("bug", "p1"), state="closed", limit=5)
    url = transport.requests[0].url
    assert "state=closed" in url
    assert "labels=bug,p1" in url


def test_get_issue() -> None:
    transport = RecordingTransport([_resp(200, _load("github_issue.json"))])
    issue = _client(transport).get_issue(1)
    assert issue.number == 1
    assert issue.body == "Users are logged out after 60s."
    assert transport.requests[0].url.endswith("/repos/o/n/issues/1")


def test_list_issues_paginates_via_link_header() -> None:
    page2 = "https://api.github.com/repos/o/n/issues?page=2"
    transport = RecordingTransport(
        [
            _resp(200, _load("github_issues.json"), {"Link": f'<{page2}>; rel="next"'}),  # type: ignore[arg-type]
            _resp(
                200,
                [
                    {
                        "id": 444,
                        "number": 4,
                        "title": "third",
                        "body": "",
                        "state": "open",
                        "labels": [],
                        "user": {"login": "dan"},
                        "html_url": "u",
                    }
                ],
            ),
        ]
    )
    issues = _client(transport).list_issues(limit=4)
    assert [i.number for i in issues] == [1, 2, 4]
    assert transport.requests[1].url == page2


def test_list_issues_stops_on_non_list_body() -> None:
    transport = RecordingTransport([_resp(200, {"message": "not a list"})])
    assert _client(transport).list_issues() == []


def test_link_header_without_next_rel_stops_pagination() -> None:
    transport = RecordingTransport([_resp(200, [], {"Link": '<https://x/last>; rel="last"'})])
    assert _client(transport).list_issues() == []
    assert len(transport.requests) == 1  # rel != "next" -> no follow-up request


def test_list_changes_maps_pull_request() -> None:
    transport = RecordingTransport([_resp(200, _load("github_pulls.json"))])
    changes = _client(transport).list_changes()
    assert len(changes) == 1
    change = changes[0]
    assert change.number == 5
    assert change.head == "fix/timeout"
    assert change.base == "main"
    assert change.state == "open"


def test_get_change() -> None:
    payload = _load("github_pulls.json")[0]  # type: ignore[index]
    transport = RecordingTransport([_resp(200, payload)])
    change = _client(transport).get_change(5)
    assert change.number == 5
    assert transport.requests[0].url.endswith("/repos/o/n/pulls/5")


def test_request_headers_include_auth_and_api_version() -> None:
    transport = RecordingTransport([_resp(200, {"login": "a"})])
    _client(transport, token="secret").whoami()
    headers = transport.requests[0].headers
    assert headers["Authorization"] == "Bearer secret"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert headers["Accept"] == "application/vnd.github+json"


def test_empty_token_omits_authorization_header() -> None:
    transport = RecordingTransport([_resp(200, {"login": "a"})])
    _client(transport, token="").whoami()
    assert "Authorization" not in transport.requests[0].headers


@pytest.mark.parametrize(
    ("status", "expected"), [(401, AuthError), (404, NotFoundError), (500, TransientError)]
)
def test_status_codes_map_to_exceptions(status: int, expected: type[Exception]) -> None:
    transport = RecordingTransport([_resp(status, {"message": "x"})])
    with pytest.raises(expected):
        _client(transport).whoami()


def test_rate_limit_exposes_retry_after() -> None:
    transport = RecordingTransport([_resp(429, {"message": "slow down"}, {"Retry-After": "30"})])
    with pytest.raises(RateLimitError) as info:
        _client(transport).whoami()
    assert info.value.retry_after == 30.0


def test_forbidden_with_retry_after_is_a_rate_limit() -> None:
    transport = RecordingTransport([_resp(403, {}, {"Retry-After": "5"})])
    with pytest.raises(RateLimitError):
        _client(transport).whoami()


def test_non_json_body_raises_transient() -> None:
    transport = RecordingTransport([Response(status=200, headers={}, body=b"<html>oops</html>")])
    with pytest.raises(TransientError):
        _client(transport).whoami()
