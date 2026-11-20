import json

import pytest

from novamind.agents import learner as learner_module
from novamind.agents.learner import LearnerAgent
from novamind.core.learning_loop import LearningLoop


def test_learn_persists_session_lesson(tmp_path, monkeypatch):
    ledger = LearningLoop(tmp_path / "experiences.jsonl")
    monkeypatch.setattr("novamind.core.learning_loop.learning_loop", ledger)
    agent = LearnerAgent()

    result = agent.learn("Fix retry handling", source="unit-test")

    assert result["ok"] is True
    assert result["learned"] == 1
    records = ledger.load_all()
    assert len(records) == 1
    assert records[0].agent == "learner"
    assert records[0].task == "Learn from unit-test"
    assert records[0].output_summary == "Fix retry handling"
    assert records[0].input_size > 0
    assert records[0].outcome == "success"


def test_learn_rejects_invalid_summary():
    agent = LearnerAgent()
    with pytest.raises(ValueError):
        agent.learn("  ")


def test_learning_loop_review_api_persists_and_skips_empty(tmp_path):
    ledger = LearningLoop(tmp_path / "experiences.jsonl")

    empty = ledger.learn_from_pr_review("org/repo", 7, [{"description": " "}])
    assert empty == {"learned": 0, "experience_id": None}
    assert ledger.load_all() == []

    result = ledger.learn_from_pr_review(
        "org/repo", 7,
        [{"description": "Missing authorization check", "severity": "high"}],
    )
    assert result["learned"] == 1
    assert len(ledger.load_all()) == 1


def test_learning_loop_feedback_api_persists(tmp_path):
    ledger = LearningLoop(tmp_path / "experiences.jsonl")

    result = ledger.record_feedback("safer retries", True)

    assert result["ok"] is True
    record = ledger.load_all()[0]
    assert record.agent == "feedback"
    assert record.user_feedback == "liked"


def test_record_feedback_reports_secondary_failure(tmp_path, monkeypatch):
    feedback_file = tmp_path / "feedback.json"
    monkeypatch.setattr(learner_module, "FEEDBACK_FILE", feedback_file)
    agent = LearnerAgent()

    def fail_record_feedback(*args, **kwargs):
        raise OSError("ledger unavailable")

    monkeypatch.setattr(
        "novamind.core.learning_loop.learning_loop.record_feedback",
        fail_record_feedback,
    )

    result = agent.record_feedback("safe retries", True)

    assert result["ok"] is True
    assert result["feedback_saved"] is True
    assert result["learning_recorded"] is False
    assert "ledger unavailable" in result["warning"]
    saved = json.loads(feedback_file.read_text(encoding="utf-8"))
    assert len(saved["entries"]) == 1
    assert agent.stats()["total_feedback"] == 1


def test_record_feedback_rolls_back_memory_when_primary_save_fails(tmp_path, monkeypatch):
    invalid_target = tmp_path / "feedback-as-directory"
    invalid_target.mkdir()
    monkeypatch.setattr(learner_module, "FEEDBACK_FILE", invalid_target)
    agent = LearnerAgent()
    before = json.dumps(agent.feedback, sort_keys=True)

    with pytest.raises((IsADirectoryError, OSError)):
        agent.record_feedback("safe retries", True)

    assert json.dumps(agent.feedback, sort_keys=True) == before


@pytest.mark.parametrize(
    ("pattern", "liked", "error"),
    [
        ("", True, ValueError),
        ("pattern", 1, TypeError),
    ],
)
def test_record_feedback_validates_input(tmp_path, monkeypatch, pattern, liked, error):
    monkeypatch.setattr(learner_module, "FEEDBACK_FILE", tmp_path / "feedback.json")
    with pytest.raises(error):
        LearnerAgent().record_feedback(pattern, liked)

def test_learning_loop_does_not_acknowledge_failed_storage(tmp_path):
    blocked_path = tmp_path / "experiences.jsonl"
    blocked_path.mkdir()
    ledger = LearningLoop(blocked_path)

    with pytest.raises(IsADirectoryError):
        ledger.record(
            agent="unit-test",
            task="persist",
            input_data="input",
            output="output",
            outcome="success",
        )


def test_learning_loop_uses_configured_storage_path(tmp_path, monkeypatch):
    configured = tmp_path / "isolated" / "experiences.jsonl"
    monkeypatch.setenv("NOVAMIND_LEARNING_LOOP_PATH", str(configured))

    ledger = LearningLoop()

    assert ledger.storage_path == configured
    assert configured.parent.is_dir()


def test_learning_loop_propagates_fsync_failure(tmp_path, monkeypatch):
    import os

    ledger = LearningLoop(tmp_path / "experiences.jsonl")

    def fail_fsync(_fd):
        raise OSError("disk flush failed")

    monkeypatch.setattr(os, "fsync", fail_fsync)

    with pytest.raises(OSError, match="disk flush failed"):
        ledger.record(
            agent="unit-test",
            task="fsync",
            input_data="input",
            output="output",
            outcome="success",
        )


def test_feedback_reports_directory_fsync_uncertainty_after_atomic_replace(
    tmp_path, monkeypatch
):
    import os

    feedback_file = tmp_path / "feedback.json"
    monkeypatch.setattr(learner_module, "FEEDBACK_FILE", feedback_file)
    agent = LearnerAgent()
    real_fsync = os.fsync
    calls = {"count": 0}

    def fail_directory_fsync(fd):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("directory sync unavailable")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_directory_fsync)

    result = agent.record_feedback("durable writes", True)

    assert result["feedback_saved"] is True
    assert result["feedback_directory_synced"] is False
    assert result["learning_recorded"] in (True, False)
    assert "directory fsync failed" in result["warning"]
    assert len(json.loads(feedback_file.read_text(encoding="utf-8"))["entries"]) == 1
    assert agent.stats()["total_feedback"] == 1
