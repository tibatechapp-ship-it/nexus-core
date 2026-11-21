from __future__ import annotations

import hashlib
import json
import math

import pytest

from novamind.core.learning_loop import LearningLoop, sanitize_learning_text


def test_record_hashes_redacted_input_and_sanitizes_outcome(tmp_path):
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
    assert experience.input_hash == hashlib.sha256(safe_input.encode("utf-8")).hexdigest()
    assert experience.input_hash != hashlib.sha256(raw_input.encode("utf-8")).hexdigest()
    assert "[REDACTED]" in experience.outcome
    persisted = loop.storage_path.read_text(encoding="utf-8")
    assert "secret-value-123" not in persisted
    assert "secret-token-value" not in persisted
    record = json.loads(persisted)
    assert record["input_size"] == len(safe_input)


@pytest.mark.parametrize("duration", [float("nan"), float("inf"), float("-inf"), -0.1, True, "1"])
def test_record_rejects_invalid_duration(tmp_path, duration):
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


@pytest.mark.parametrize("tags", ["", {}, 0, False])
def test_record_rejects_falsey_non_sequence_tags(tmp_path, tags):
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


def test_record_rejects_input_larger_than_one_mib(tmp_path):
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
