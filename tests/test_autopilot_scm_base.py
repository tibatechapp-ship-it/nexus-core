"""Tests for the autopilot SCM contracts, shared helpers and transports (Slice 1).

Everything here runs offline: the transports are exercised through a monkeypatched
``urllib.request.urlopen`` or the in-memory :class:`RecordingTransport`.
"""

from __future__ import annotations

import io
import json
import urllib.error
from dataclasses import FrozenInstanceError

import pytest

from src.novamind.autopilot.scm import (
    AuthError,
    Issue,
    NotFoundError,
    RateLimitError,
    RecordedRequest,
    RecordingTransport,
    Response,
    SCMError,
    TransientError,
    UrllibTransport,
    as_int,
    error_for_status,
    label_names,
    normalize_state,
    retry_after_seconds,
)


def _resp(status: int, payload: object = None, headers: dict[str, str] | None = None) -> Response:
    body = b"" if payload is None else json.dumps(payload).encode()
    return Response(status=status, headers=headers or {}, body=body)


# ── error_for_status ─────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("status", "retry", "expected"),
    [
        (0, 0.0, TransientError),
        (404, 0.0, NotFoundError),
        (401, 0.0, AuthError),
        (403, 0.0, AuthError),
        (403, 30.0, RateLimitError),
        (429, 0.0, RateLimitError),
        (500, 0.0, TransientError),
        (503, 0.0, TransientError),
        (418, 0.0, SCMError),
    ],
)
def test_error_for_status_maps(status: int, retry: float, expected: type[SCMError]) -> None:
    err = error_for_status(status, retry_after=retry)
    assert type(err) is expected
    assert err.status == status


def test_error_for_status_default_message() -> None:
    assert "429" in str(error_for_status(429))


def test_rate_limit_carries_retry_after() -> None:
    err = error_for_status(429, retry_after=12.5)
    assert isinstance(err, RateLimitError)
    assert err.retry_after == 12.5


# ── shared helpers ───────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "expected"),
    [("opened", "open"), ("open", "open"), ("closed", "closed"), ("merged", "merged"), ("zzz", "zzz")],
)
def test_normalize_state(raw: str, expected: str) -> None:
    assert normalize_state(raw) == expected


def test_label_names_dict_and_str() -> None:
    assert label_names([{"name": "bug"}, {"name": "p1"}]) == ("bug", "p1")
    assert label_names(["bug", "p1"]) == ("bug", "p1")


def test_label_names_empty_and_none() -> None:
    assert label_names([]) == ()
    assert label_names(None) == ()


@pytest.mark.parametrize(
    ("value", "expected"), [(7, 7), ("8", 8), (None, 0), ("abc", 0), ("", 0)]
)
def test_as_int(value: object, expected: int) -> None:
    assert as_int(value) == expected


def test_as_int_custom_default() -> None:
    assert as_int("abc", -1) == -1


@pytest.mark.parametrize(
    ("headers", "expected"),
    [({"Retry-After": "12"}, 12.0), ({"retry-after": "3"}, 3.0), ({}, 0.0), ({"Retry-After": "soon"}, 0.0)],
)
def test_retry_after_seconds(headers: dict[str, str], expected: float) -> None:
    assert retry_after_seconds(headers) == expected


# ── value objects ────────────────────────────────────────────────────────────
def test_models_are_frozen_and_equal() -> None:
    a = Issue("github", 1, 1, "t", "b", "open", ("bug",), "alice", "u")
    b = Issue("github", 1, 1, "t", "b", "open", ("bug",), "alice", "u")
    assert a == b
    with pytest.raises(FrozenInstanceError):
        a.title = "x"  # type: ignore[misc]


# ── RecordingTransport ───────────────────────────────────────────────────────
def test_recording_transport_records_and_replays() -> None:
    transport = RecordingTransport([_resp(200, {"ok": True})])
    result = transport.request("GET", "https://x/y", headers={"A": "b"}, timeout=5.0)
    assert result.status == 200
    assert transport.requests == [RecordedRequest("GET", "https://x/y", {"A": "b"}, None, 5.0)]


def test_recording_transport_queue() -> None:
    transport = RecordingTransport()
    transport.queue(_resp(200), _resp(204))
    assert transport.request("GET", "u", headers={}).status == 200
    assert transport.request("GET", "u", headers={}).status == 204


def test_recording_transport_exhausted_raises() -> None:
    with pytest.raises(AssertionError):
        RecordingTransport().request("GET", "u", headers={})


# ── UrllibTransport (monkeypatched urlopen) ──────────────────────────────────
class _FakeResponse:
    status = 200
    headers = {"X-Test": "1"}

    def read(self) -> bytes:
        return b'{"ok": true}'

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def test_urllib_transport_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(req: object, timeout: object = None, context: object = None) -> _FakeResponse:
        captured["url"] = req.full_url  # type: ignore[attr-defined]
        captured["method"] = req.get_method()  # type: ignore[attr-defined]
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}  # type: ignore[attr-defined]
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = UrllibTransport().request(
        "GET", "https://api.github.com/user", headers={"Authorization": "Bearer x"}
    )
    assert result.status == 200
    assert result.body == b'{"ok": true}'
    assert result.headers == {"X-Test": "1"}
    assert captured["method"] == "GET"
    assert captured["url"] == "https://api.github.com/user"
    assert captured["headers"]["authorization"] == "Bearer x"  # type: ignore[index]


def test_urllib_transport_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: object, timeout: object = None, context: object = None) -> object:
        raise urllib.error.HTTPError(
            req.full_url, 404, "Not Found", {"X-E": "y"}, io.BytesIO(b"nope")  # type: ignore[attr-defined]
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = UrllibTransport().request("GET", "https://x/1", headers={})
    assert result.status == 404
    assert result.body == b"nope"
    assert result.headers == {"X-E": "y"}


def test_urllib_transport_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: object, timeout: object = None, context: object = None) -> object:
        raise urllib.error.URLError("boom")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(TransientError) as info:
        UrllibTransport().request("GET", "https://x", headers={})
    assert info.value.status == 0
