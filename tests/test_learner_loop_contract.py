from __future__ import annotations

import json
from pathlib import Path

import pytest

from novamind.core.learning_loop import LearningLoop, LearningStorageError
import novamind.core.learning_loop as learning_loop_module
from novamind.agents import learner as learner_module


def test_review_learning_persists_and_redacts_credentials(tmp_path: Path) -> None:
    loop = LearningLoop(tmp_path / "experiences.jsonl")
    result = loop.learn_from_pr_review(
        repo="example/repo",
        pr_num=42,
        issues=[{
            "description": "Found api_key=super-secret-token in config",
            "severity": "high",
            "confidence": 0.9,
        }],
    )

    assert result["issues_recorded"] == 1
    experience = loop.load_all()[0]
    assert experience.agent == "learner"
    assert experience.task == "pr_review_learning"
    assert "super-secret-token" not in experience.output_summary
    assert "api_key=[REDACTED]" in experience.output_summary
    assert "confidence 0.90" in experience.output_summary
    stored = json.loads((tmp_path / "experiences.jsonl").read_text(encoding="utf-8"))
    assert "super-secret-token" not in json.dumps(stored)
    assert stored["input_size"] > 0


def test_review_learning_validates_contract(tmp_path: Path) -> None:
    loop = LearningLoop(tmp_path / "experiences.jsonl")
    with pytest.raises(ValueError, match="pr_num"):
        loop.learn_from_pr_review("repo", -1, [])
    with pytest.raises(ValueError, match="issues"):
        loop.learn_from_pr_review("repo", 1, ["bad"])
    with pytest.raises(ValueError, match="confidence"):
        loop.learn_from_pr_review("repo", 1, [{"confidence": 1.5}])


def test_feedback_is_recorded_as_learning_experience(tmp_path: Path) -> None:
    loop = LearningLoop(tmp_path / "experiences.jsonl")
    exp = loop.record_feedback("use typed interfaces", True)
    assert exp.user_feedback == "liked"
    assert "use typed interfaces" in exp.output_summary
    assert "feedback" in exp.tags
    assert loop.load_all()[0].task == "user_feedback"


def test_record_raises_when_storage_fails(tmp_path: Path) -> None:
    storage_path = tmp_path / "not-a-file"
    storage_path.mkdir()
    loop = LearningLoop(storage_path)
    with pytest.raises(LearningStorageError, match="persist"):
        loop.record(
            agent="test",
            task="storage failure",
            input_data="input",
            output="output",
            outcome="success",
        )


def test_learner_agent_learn_uses_supported_learning_api(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    loop = LearningLoop(tmp_path / "experiences.jsonl")
    monkeypatch.setattr(learner_module, "FEEDBACK_FILE", tmp_path / "feedback.json")
    monkeypatch.setattr(learning_loop_module, "learning_loop", loop)
    agent = learner_module.LearnerAgent()

    result = agent.learn("session summary", source="unit-test", min_confidence=0.8)

    assert result["ok"] is True
    assert result["issues_recorded"] == 1
    assert loop.load_all()[0].agent == "learner"


def test_feedback_reports_secondary_persistence_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    loop = LearningLoop(tmp_path / "experiences.jsonl")
    monkeypatch.setattr(learner_module, "FEEDBACK_FILE", tmp_path / "feedback.json")
    monkeypatch.setattr(learning_loop_module, "learning_loop", loop)
    agent = learner_module.LearnerAgent()

    def fail_feedback(pattern: str, liked: bool) -> None:
        raise LearningStorageError("secondary store unavailable")

    monkeypatch.setattr(loop, "record_feedback", fail_feedback)
    result = agent.record_feedback("api_key=super-secret", True, context="token=another-secret")

    assert result["ok"] is True
    assert result["feedback_saved"] is True
    assert result["learning_recorded"] is False
    assert "secondary store unavailable" in result["warning"]
    feedback_text = (tmp_path / "feedback.json").read_text(encoding="utf-8")
    assert "super-secret" not in feedback_text
    assert "another-secret" not in feedback_text
    assert "api_key=[REDACTED]" in feedback_text
