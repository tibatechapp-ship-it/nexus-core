from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.fleet import promotion


def test_eval_gate_uses_injected_runner_and_normalizes_result() -> None:
    calls = []

    def runner(framework, name, category):
        calls.append((framework, name, category))
        return {
            "eval_suite": "passed",
            "passed": "3",
            "total": "4",
            "reason": "verified",
            "ignored": "field",
        }

    result = promotion.eval_gate("native", "agent-a", category="coding", runner=runner)
    assert calls == [("native", "agent-a", "coding")]
    assert result == {
        "agent": "agent-a",
        "framework": "native",
        "category": "coding",
        "eval_suite": "passed",
        "passed": 3,
        "total": 4,
        "reason": "verified",
    }


def test_eval_gate_reports_runner_exception_and_missing_fields() -> None:
    def broken(*_args):
        raise RuntimeError("backend unavailable")

    failed = promotion.eval_gate("f", "a", category="meta", runner=broken)
    assert failed["eval_suite"] == "failed"
    assert failed["passed"] == 0
    assert "RuntimeError" in failed["reason"]

    empty = promotion.eval_gate("f", "a", category="meta", runner=lambda *_: {})
    assert empty["eval_suite"] == "failed"
    assert empty["passed"] == 0
    assert empty["total"] == 0


def test_category_lookup_returns_inventory_category_and_meta_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.fleet.inventory.build_inventory",
        lambda: [SimpleNamespace(framework="f", name="a", category="coding")],
    )
    assert promotion._category_of("f", "a") == "coding"
    assert promotion._category_of("f", "missing") == "meta"

    def inventory_failure():
        raise RuntimeError("inventory unavailable")

    monkeypatch.setattr("src.fleet.inventory.build_inventory", inventory_failure)
    assert promotion._category_of("f", "a") == "meta"


@pytest.mark.parametrize(
    ("current", "target", "suite", "allowed"),
    [
        ("B", "S", "passed", True),
        ("B", "S", "failed", False),
        ("B", "S", "unmeasured", False),
        ("B", "S", None, False),
        ("B", "A", None, True),
        ("S", "A", "passed", False),
        ("S", "S", "passed", True),
    ],
)
def test_promotion_gate_enforces_evaluation_and_no_implicit_s_demotion(
    current, target, suite, allowed
) -> None:
    result = promotion.promotion_gate(
        framework="f",
        name="agent",
        current_tier=current,
        target_tier=target,
        eval_suite=suite,
    )
    assert result["allowed"] is allowed
    assert result["agent"] == "agent"
    assert result["eval_suite"] == (suite or "unmeasured")
    assert result["reason"] == "ok" if allowed else result["reason"].startswith("refused:")


def test_read_log_handles_missing_invalid_and_valid_files(tmp_path) -> None:
    missing = tmp_path / "missing.json"
    assert promotion.read_log(missing) == []

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    assert promotion.read_log(malformed) == []

    wrong_shape = tmp_path / "wrong.json"
    wrong_shape.write_text(json.dumps([]), encoding="utf-8")
    assert promotion.read_log(wrong_shape) == []

    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps({"log": [{"agent": "a"}]}), encoding="utf-8")
    assert promotion.read_log(valid) == [{"agent": "a"}]


def test_append_log_stamps_defaults_preserves_entries_and_creates_parent(tmp_path) -> None:
    target = tmp_path / "nested" / "reports" / "promotion.json"
    result = promotion.append_log({"agent": "a"}, target)
    assert len(result) == 1
    assert result[0]["agent"] == "a"
    assert result[0]["eval_suite"] == "unmeasured"
    assert result[0]["ts"]
    persisted = json.loads(target.read_text(encoding="utf-8"))
    assert persisted == {"log": result}

    second = promotion.append_log({"agent": "b", "eval_suite": "passed"}, target)
    assert [item["agent"] for item in second] == ["a", "b"]
    assert second[1]["eval_suite"] == "passed"
    assert second[1]["ts"]
