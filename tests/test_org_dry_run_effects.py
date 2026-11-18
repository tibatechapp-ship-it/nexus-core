"""Offline contract tests for the explicit dry-run effect adapter."""
from __future__ import annotations

import pytest

from src.org.dry_run_effects import DryRunEffectAdapter


def test_dry_run_records_request_and_returns_explicit_simulation_marker() -> None:
    adapter = DryRunEffectAdapter(["comment"])
    result = adapter.dispatch(
        "comment", {"repository": "owner/repo", "body": "hello"},
        idempotency_key=None,
    )

    assert result["dry_run"] is True
    assert result["simulated"] is True
    assert result["provider_id"] == "dry-run"
    assert result["operation_name"] == "comment"
    assert len(result["request_fingerprint"]) == 64
    assert adapter.calls[0]["request"] == {
        "repository": "owner/repo", "body": "hello",
    }


def test_dry_run_is_allow_listed() -> None:
    adapter = DryRunEffectAdapter(["comment"])
    with pytest.raises(ValueError, match="undeclared"):
        adapter.dispatch("delete_repository", {}, idempotency_key=None)
    assert adapter.calls == ()


def test_dry_run_rejects_provider_idempotency_key() -> None:
    adapter = DryRunEffectAdapter(["comment"])
    with pytest.raises(ValueError, match="does not accept"):
        adapter.dispatch("comment", {}, idempotency_key="key")
    assert adapter.calls == ()


def test_dry_run_rejects_non_finite_json() -> None:
    adapter = DryRunEffectAdapter(["comment"])
    with pytest.raises(ValueError, match="finite JSON"):
        adapter.dispatch("comment", {"amount": float("nan")}, idempotency_key=None)
    assert adapter.calls == ()


def test_dry_run_call_history_is_defensively_copied() -> None:
    adapter = DryRunEffectAdapter(["comment"])
    adapter.dispatch("comment", {"nested": {"value": 1}}, idempotency_key=None)

    exposed = adapter.calls
    exposed[0]["request"]["nested"]["value"] = 99
    assert adapter.calls[0]["request"]["nested"]["value"] == 1


@pytest.mark.parametrize("operations", [[], [""], ["comment", "comment"]])
def test_dry_run_rejects_invalid_operation_declarations(operations) -> None:
    with pytest.raises(ValueError):
        DryRunEffectAdapter(operations)
