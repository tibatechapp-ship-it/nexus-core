from __future__ import annotations

import json

import pytest

from novamind.agents import learner as learner_module
import novamind.core.learning_loop as learning_loop_module
from novamind.core.learning_loop import LearningLoop


def test_session_learning_redacts_persistence_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    loop = LearningLoop(tmp_path / "experiences.jsonl")
    monkeypatch.setattr(learning_loop_module, "learning_loop", loop)
    monkeypatch.setattr(learner_module, "FEEDBACK_FILE", tmp_path / "feedback.json")

    def fail_record(*args, **kwargs):
        raise OSError("disk write failed token=private-secret")

    monkeypatch.setattr(loop, "record", fail_record)
    result = learner_module.LearnerAgent().learn("safe lesson")

    assert result["ok"] is False
    assert "private-secret" not in result["error"]
    assert "token=[REDACTED]" in result["error"]


def test_secondary_feedback_error_is_redacted_and_primary_feedback_survives(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    loop = LearningLoop(tmp_path / "experiences.jsonl")
    feedback_file = tmp_path / "feedback.json"
    monkeypatch.setattr(learning_loop_module, "learning_loop", loop)
    monkeypatch.setattr(learner_module, "FEEDBACK_FILE", feedback_file)

    def fail_feedback(*args, **kwargs):
        raise OSError("secondary write failed api_key=private-secret")

    monkeypatch.setattr(loop, "record_feedback", fail_feedback)
    result = learner_module.LearnerAgent().record_feedback(
        "pattern", True, context="safe context"
    )

    assert result["feedback_saved"] is True
    assert result["learning_recorded"] is False
    assert "private-secret" not in result["warning"]
    assert "api_key=[REDACTED]" in result["warning"]
    saved = json.loads(feedback_file.read_text(encoding="utf-8"))
    assert saved["entries"][0]["pattern"] == "pattern"
