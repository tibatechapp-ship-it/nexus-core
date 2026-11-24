from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import novamind.core.learning_loop as learning_loop_module
from novamind.core.learning_loop import LearningLoop, LearningStorageError
from novamind.agents import learner as learner_module


def test_review_learning_keeps_classifications_not_source_secrets(tmp_path: Path) -> None:
    loop = LearningLoop(tmp_path / "experiences.jsonl")
    result = loop.learn_from_pr_review(
        repo="example/repo",
        pr_num=42,
        issues=[{
            "category": "security",
            "severity": "high",
            "rule_id": "credential-leak",
            "description": "api_key=super-secret-token",
        }],
    )

    assert result["learned"] == 1
    experience = loop.load_all()[0]
    assert experience.agent == "pr_reviewer"
    assert "security/high/credential-leak" in experience.output_summary
    assert "super-secret-token" not in experience.output_summary
    stored = json.loads((tmp_path / "experiences.jsonl").read_text(encoding="utf-8"))
    assert "super-secret-token" not in json.dumps(stored)
    assert "api_key=super-secret-token" not in json.dumps(stored)


def test_review_learning_validates_contract(tmp_path: Path) -> None:
    loop = LearningLoop(tmp_path / "experiences.jsonl")
    with pytest.raises(ValueError, match="pr_num"):
        loop.learn_from_pr_review("repo", -1, [])
    with pytest.raises(TypeError, match="issues"):
        loop.learn_from_pr_review("repo", 1, "bad")
    assert loop.learn_from_pr_review("repo", 1, [{}])["learned"] == 0


def test_feedback_is_recorded_as_learning_experience(tmp_path: Path) -> None:
    loop = LearningLoop(tmp_path / "experiences.jsonl")
    result = loop.record_feedback("api_key=super-secret", True, source="unit-test")
    assert result["recorded"] is True
    experience = loop.load_all()[0]
    assert experience.user_feedback == "liked"
    assert "api_key=[REDACTED]" in experience.output_summary
    assert "super-secret" not in experience.output_summary


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


def test_learner_agent_learn_uses_canonical_experience_api(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    loop = LearningLoop(tmp_path / "experiences.jsonl")
    monkeypatch.setattr(learner_module, "FEEDBACK_FILE", tmp_path / "feedback.json")
    monkeypatch.setattr(learning_loop_module, "learning_loop", loop)
    agent = learner_module.LearnerAgent()

    result = agent.learn("session summary", source="unit-test", min_confidence=0.8)

    assert result["ok"] is True
    experience = loop.load_all()[0]
    assert experience.task == "session_learning"
    assert "confidence:0.80" in experience.tags
    assert "session summary" in experience.output_summary


def test_feedback_reports_secondary_persistence_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    loop = LearningLoop(tmp_path / "experiences.jsonl")
    monkeypatch.setattr(learner_module, "FEEDBACK_FILE", tmp_path / "feedback.json")
    monkeypatch.setattr(learning_loop_module, "learning_loop", loop)
    agent = learner_module.LearnerAgent()

    def fail_feedback(
        pattern: str, liked: bool, context: str = "", source: str = "user"
    ) -> None:
        raise LearningStorageError("secondary store unavailable api_key=secondary-secret")

    monkeypatch.setattr(loop, "record_feedback", fail_feedback)
    result = agent.record_feedback(
        "api_key=super-secret", True, context="token=another-secret"
    )

    assert result["ok"] is True
    assert result["feedback_saved"] is True
    assert result["learning_recorded"] is False
    assert "secondary store unavailable" in result["warning"]
    assert "secondary-secret" not in result["warning"]
    assert "api_key=[REDACTED]" in result["warning"]
    feedback_text = (tmp_path / "feedback.json").read_text(encoding="utf-8")
    assert "super-secret" not in feedback_text
    assert "another-secret" not in feedback_text
    assert "api_key=[REDACTED]" in feedback_text


def test_learner_error_response_redacts_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    loop = LearningLoop(tmp_path / "experiences.jsonl")
    monkeypatch.setattr(learner_module, "FEEDBACK_FILE", tmp_path / "feedback.json")
    monkeypatch.setattr(learning_loop_module, "learning_loop", loop)

    def fail_record(*args, **kwargs):
        raise LearningStorageError("write failed token=private-token")

    monkeypatch.setattr(loop, "record", fail_record)
    result = learner_module.LearnerAgent().learn("safe summary")

    assert result["ok"] is False
    assert "private-token" not in result["error"]
    assert "token=[REDACTED]" in result["error"]


def test_record_hashes_redacted_input_and_sanitizes_outcome(tmp_path: Path) -> None:
    from novamind.core.learning_loop import sanitize_learning_text

    loop = LearningLoop(tmp_path / "experiences.jsonl")
    raw_input = "request token=secret-value-123"
    raw_outcome = "authorization: Bearer secret-token-value"
    experience = loop.record(
        agent="test-agent",
        task="credential redaction",
        input_data=raw_input,
        output={"summary": "completed"},
        outcome=raw_outcome,
        input_summary=raw_input,
    )

    safe_input = sanitize_learning_text(raw_input, max_length=None)
    assert experience.input_hash == hashlib.sha256(
        safe_input.encode("utf-8")
    ).hexdigest()
    assert experience.input_hash != __import__("hashlib").sha256(
        raw_input.encode("utf-8")
    ).hexdigest()
    assert "[REDACTED]" in experience.outcome
    assert "secret-value-123" not in experience.input_summary
    persisted = loop.storage_path.read_text(encoding="utf-8")
    assert "secret-value-123" not in persisted
    assert "secret-token-value" not in persisted
    record = json.loads(persisted)
    assert record["input_size"] == len(safe_input)


@pytest.mark.parametrize(
    "duration",
    [float("nan"), float("inf"), float("-inf"), -0.1, True, "1"],
)
def test_record_rejects_invalid_duration(tmp_path: Path, duration) -> None:
    loop = LearningLoop(tmp_path / "experiences.jsonl")
    with pytest.raises(ValueError, match="duration must be a finite"):
        loop.record(
            agent="test-agent",
            task="validate duration",
            input_data="input",
            output={"summary": "completed"},
            outcome="success",
            duration=duration,
        )
    assert not loop.storage_path.exists()


@pytest.mark.parametrize("tags", ["", {}, 0, False, [""]])
def test_record_rejects_invalid_tags(tmp_path: Path, tags) -> None:
    loop = LearningLoop(tmp_path / "experiences.jsonl")
    with pytest.raises(TypeError, match="tags must be a list"):
        loop.record(
            agent="test-agent",
            task="validate tags",
            input_data="input",
            output={"summary": "completed"},
            outcome="success",
            tags=tags,
        )
    assert not loop.storage_path.exists()


def test_record_rejects_input_larger_than_one_mib(tmp_path: Path) -> None:
    loop = LearningLoop(tmp_path / "experiences.jsonl")
    with pytest.raises(ValueError, match="1 MiB"):
        loop.record(
            agent="test-agent",
            task="bound input",
            input_data="x" * (1_048_576 + 1),
            output={"summary": "completed"},
            outcome="success",
        )
    assert not loop.storage_path.exists()


def test_record_rejects_non_string_metadata_before_writing(tmp_path: Path) -> None:
    loop = LearningLoop(tmp_path / "experiences.jsonl")
    with pytest.raises(TypeError, match="provider, model"):
        loop.record(
            agent="test-agent",
            task="validate metadata",
            input_data="input",
            output={"summary": "completed"},
            outcome="success",
            provider=object(),
        )
    assert not loop.storage_path.exists()
