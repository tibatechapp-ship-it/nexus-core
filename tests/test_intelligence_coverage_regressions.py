"""Targeted edge-case coverage for intelligence evidence contracts."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.intelligence.behavior import BehaviorContractError, digest_payload
from src.intelligence.capture import CaptureError, _canonical_bytes, sanitize_payload
from src.intelligence.mission import BehaviorCaseSpec, MissionBehaviorError
from src.intelligence.replay import BehaviorReplayError, ReplayCommandCase


def test_sanitizer_handles_nested_values_and_all_supported_secret_forms() -> None:
    token = "ghp_" + "a" * 30
    github_pat = "github_pat_" + "b" * 30
    payload = {
        "nested": [{"safe": "ok", "refresh_token": "refresh-value"}],
        "text": (
            "Bearer abc.def.ghi api_key=key-value token:plain-token "
            + token + " " + github_pat + " AKIA1234567890ABCDEF"
        ),
        "private": "-----BEGIN PRIVATE KEY-----\nsecret-material\n-----END PRIVATE KEY-----",
    }
    clean = sanitize_payload(payload)
    assert clean["nested"][0]["safe"] == "ok"
    assert clean["nested"][0]["refresh_token"] == "[REDACTED]"
    serialized = repr(clean)
    for secret in (
        "refresh-value", "abc.def.ghi", "key-value", "plain-token",
        token, github_pat, "AKIA1234567890ABCDEF", "secret-material",
    ):
        assert secret not in serialized


def test_sanitizer_redacts_non_string_secret_field_names() -> None:
    assert sanitize_payload({"client_secret": {"nested": "value"}}) == {
        "client_secret": "[REDACTED]"
    }


def test_capture_canonicalization_rejects_nan_and_oversized_payloads() -> None:
    with pytest.raises(CaptureError, match="canonical JSON"):
        _canonical_bytes({"number": float("nan")})
    with pytest.raises(CaptureError, match="1 MiB"):
        _canonical_bytes("x" * (1024 * 1024))


def test_behavior_digest_rejects_noncanonical_and_oversized_payloads() -> None:
    with pytest.raises(BehaviorContractError, match="canonical JSON"):
        digest_payload({"number": float("inf")})
    with pytest.raises(BehaviorContractError, match="1 MiB"):
        digest_payload("x" * (1024 * 1024))


@pytest.mark.parametrize(
    "case_id,argv,timeout,payload",
    [
        ("", ("cat", "{behavior_input}"), 10, {}),
        ("valid", (), 10, {}),
        ("valid", ("cat", "\x00", "{behavior_input}"), 10, {}),
        ("valid", ("cat", "{behavior_input}"), True, {}),
        ("valid", ("cat", "{behavior_input}"), 301, {}),
        ("valid", ("cat", "{behavior_input}"), 10, object()),
    ],
)
def test_behavior_case_spec_rejects_invalid_contracts(
    case_id: str, argv: tuple[str, ...], timeout: int, payload: object
) -> None:
    with pytest.raises(MissionBehaviorError):
        BehaviorCaseSpec(case_id, argv, payload, timeout)


def test_replay_case_rejects_bad_workspace_and_payload(tmp_path: Path) -> None:
    with pytest.raises(BehaviorReplayError, match="existing non-symlink"):
        ReplayCommandCase(
            "case", ("cat",), tmp_path / "missing", {},
        )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(BehaviorReplayError, match="filesystem path"):
        ReplayCommandCase("case", ("cat",), None, {})  # type: ignore[arg-type]
    with pytest.raises(BehaviorReplayError, match="timeout"):
        ReplayCommandCase("case", ("cat",), workspace, {}, True)
    with pytest.raises(BehaviorReplayError, match="input fixture"):
        ReplayCommandCase("case", ("cat",), workspace, object())
