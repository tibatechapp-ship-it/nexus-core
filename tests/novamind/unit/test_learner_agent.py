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
    assert records[0].input_summary == "Fix retry handling"
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
    records = ledger.load_all()
    assert len(records) == 1
    assert "Missing authorization check" in records[0].input_summary


def test_learning_loop_feedback_api_persists(tmp_path):
    ledger = LearningLoop(tmp_path / "experiences.jsonl")

    result = ledger.record_feedback("safer retries", True)

    assert result["ok"] is True
    record = ledger.load_all()[0]
    assert record.agent == "feedback"
    assert record.user_feedback == "liked"
    assert record.input_summary == "safer retries"


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


def test_learning_loop_persists_sanitized_review_context(tmp_path):
    ledger = LearningLoop(tmp_path / "experiences.jsonl")
    secret = "super-secret-value-123"
    token = "sk-" + "A" * 30

    ledger.learn_from_pr_review(
        "org/repo",
        9,
        [{
            "description": f"Leaked api_key={secret} and provider token {token}",
            "severity": "critical",
        }],
    )

    record = ledger.load_all()[0]
    assert "[REDACTED]" in record.input_summary
    assert secret not in record.input_summary
    assert token not in record.input_summary


def test_learning_loop_redacts_other_persisted_text_fields(tmp_path):
    ledger = LearningLoop(tmp_path / "experiences.jsonl")
    secret = "another-secret-987"

    ledger.record(
        agent="unit-test",
        task=f"Investigate password={secret}",
        input_data="hashed-only input",
        output={"summary": f"token={secret}"},
        outcome="success",
        error=f"authorization={secret}",
    )

    record = ledger.load_all()[0]
    assert secret not in record.task
    assert secret not in record.output_summary
    assert secret not in record.error
    assert "[REDACTED]" in record.task
    assert "[REDACTED]" in record.output_summary
    assert "[REDACTED]" in record.error


def test_learner_feedback_redacts_secrets_before_primary_save(tmp_path, monkeypatch):
    feedback_file = tmp_path / "feedback.json"
    monkeypatch.setattr(learner_module, "FEEDBACK_FILE", feedback_file)
    agent = LearnerAgent()
    secret = "feedback-secret-987"

    result = agent.record_feedback(f"api_key={secret}", True, context=f"token={secret}")

    saved = json.loads(feedback_file.read_text(encoding="utf-8"))
    assert result["feedback_saved"] is True
    assert secret not in feedback_file.read_text(encoding="utf-8")
    assert "[REDACTED]" in saved["entries"][0]["pattern"]
    assert "[REDACTED]" in saved["entries"][0]["context"]


def test_learning_text_redacts_bearer_and_jwt_tokens():
    from novamind.core.learning_loop import sanitize_learning_text

    bearer = "Bearer " + "B" * 40
    jwt = "eyJ" + "a" * 20 + "." + "b" * 20 + "." + "c" * 20
    sanitized = sanitize_learning_text(
        f"Authorization: {bearer}; session={jwt}"
    )

    assert bearer not in sanitized
    assert jwt not in sanitized
    assert sanitized.count("[REDACTED]") == 2


def test_concurrent_feedback_updates_do_not_lose_entries(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    feedback_file = tmp_path / "feedback.json"
    monkeypatch.setattr(learner_module, "FEEDBACK_FILE", feedback_file)
    agent = LearnerAgent()

    def write_feedback(index):
        return agent.record_feedback("concurrent pattern", index % 2 == 0)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(write_feedback, range(24)))

    saved = json.loads(feedback_file.read_text(encoding="utf-8"))
    assert len(results) == 24
    assert len(saved["entries"]) == 24
    weight = saved["pattern_weights"]["concurrent pattern"]
    assert weight == {"likes": 12, "dislikes": 12, "net": 0}
    assert agent.stats()["total_feedback"] == 24
