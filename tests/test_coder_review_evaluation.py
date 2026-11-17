"""Tests for independent review and isolated repair evaluation."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.coder.evaluation import EvaluationError, evaluate_tasks
from src.coder.reviewer import ReviewError, review_patch


def _verdict(**overrides):
    value = {
        "decision": "approve", "summary": "Patch is supported by evidence.",
        "findings": [], "tests_required": ["pytest -q"], "confidence": 0.93,
    }
    value.update(overrides)
    return value


def test_reviewer_requires_distinct_provider_identity():
    with pytest.raises(ReviewError, match="distinct"):
        asyncio.run(review_patch(
            "diff", "tests pass", lambda _: _verdict(),
            author_provider_id="provider/model-a",
            reviewer_provider_id="provider/model-a",
        ))


def test_reviewer_normalizes_high_severity_approval_to_changes():
    result = asyncio.run(review_patch(
        "diff", "evidence",
        lambda _: _verdict(findings=[{
            "severity": "high", "file": "src/a.py", "line": 8,
            "issue": "Missing authorization", "evidence": "No check before write",
        }]),
        author_provider_id="author/model", reviewer_provider_id="reviewer/model",
    ))
    assert result["decision"] == "request_changes"
    assert result["independent"] is True


def test_reviewer_rejects_malformed_verdict():
    with pytest.raises(ReviewError):
        asyncio.run(review_patch(
            "diff", "", lambda _: {"decision": "maybe"},
            author_provider_id="a", reviewer_provider_id="b",
        ))


def _task():
    return {
        "id": "fix-greeting",
        "files": {"app.py": 'def greet():\n    return "hello"\n'},
        "patches": [{"path": "app.py", "find": 'return "hello"',
                     "replace": 'return "hello world"'}],
        "expected_files": {"app.py": 'def greet():\n    return "hello world"\n'},
        "test_command": ["python", "-m", "pytest", "-q"],
    }


def test_evaluator_fails_closed_without_container_executor():
    result = evaluate_tasks([_task()])
    assert result["ok"] is False
    assert result["tasks_passed"] == 0
    assert "isolated executor" in result["error"]


def test_evaluator_uses_injected_executor_and_reports_metrics():
    calls = []

    def executor(command, workspace, **kwargs):
        calls.append((command, Path(workspace, "app.py").read_text(), kwargs))
        return {"ok": True, "exit_code": 0, "timeout": False, "stdout": "2 passed"}

    result = evaluate_tasks([_task()], executor=executor, image="pinned@sha256:x",
                             enabled=True, approved=True)
    assert result["ok"] is True
    assert result["pass_rate"] == 1.0
    assert result["tasks_passed"] == 1
    assert calls[0][1] == 'def greet():\n    return "hello world"\n'
    assert calls[0][0] == ["python", "-m", "pytest", "-q"]


def test_evaluator_rejects_non_unique_patch_match():
    task = _task()
    task["files"]["app.py"] = 'return "hello"\nreturn "hello"\n'
    with pytest.raises(EvaluationError, match="exactly once"):
        evaluate_tasks([task], executor=lambda *a, **k: {"ok": True})


def test_evaluator_rejects_path_traversal():
    task = _task()
    task["files"] = {"../escape.py": "bad"}
    with pytest.raises(EvaluationError, match="unsafe"):
        evaluate_tasks([task], executor=lambda *a, **k: {"ok": True})
