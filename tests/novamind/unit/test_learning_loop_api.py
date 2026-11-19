from __future__ import annotations

import json
import hashlib

import pytest

from novamind.core.learning_loop import LearningLoop


def test_learn_from_pr_review_persists_normalized_findings(tmp_path):
    loop = LearningLoop(tmp_path / "experiences.jsonl")

    result = loop.learn_from_pr_review(
        repo="owner/project",
        pr_num=17,
        issues=[
            {"description": "Missing authorization check", "severity": "high"},
            {"message": "Potential resource leak"},
            {"description": "   "},
        ],
    )

    assert result["learned"] == 2
    assert result["experience_id"]
    records = [json.loads(line) for line in loop.storage_path.read_text().splitlines()]
    assert len(records) == 1
    assert records[0]["agent"] == "pr-review-learner"
    assert records[0]["tags"] == ["pr-review", "review-learning"]
    expected_payload = json.dumps(
        [
            {"description": "Missing authorization check", "severity": "high"},
            {"description": "Potential resource leak", "severity": "info"},
        ],
        ensure_ascii=False,
        sort_keys=True,
    )\n    assert records[0]["input_hash"] == hashlib.sha256(expected_payload.encode()).hexdigest()


def test_learn_from_pr_review_empty_findings_do_not_write(tmp_path):
    loop = LearningLoop(tmp_path / "experiences.jsonl")

    result = loop.learn_from_pr_review("owner/project", 0, [])

    assert result == {"learned": 0, "experience_id": None}
    assert not loop.storage_path.exists()


@pytest.mark.parametrize(
    "repo,pr_num,issues,error",
    [
        ("", 1, [], ValueError),
        ("owner/project", True, [], ValueError),
        ("owner/project", -1, [], ValueError),
        ("owner/project", 1, {}, TypeError),
        ("owner/project", 1, ["not-a-mapping"], TypeError),
    ],
)
def test_learn_from_pr_review_rejects_invalid_input(tmp_path, repo, pr_num, issues, error):
    loop = LearningLoop(tmp_path / "experiences.jsonl")
    with pytest.raises(error):
        loop.learn_from_pr_review(repo, pr_num, issues)


def test_record_feedback_persists_feedback_without_optional_providers(tmp_path):
    loop = LearningLoop(tmp_path / "experiences.jsonl")

    result = loop.record_feedback("prefer deterministic validation", True)

    assert result["ok"] is True
    assert result["experience_id"]
    record = json.loads(loop.storage_path.read_text().splitlines()[0])
    assert record["agent"] == "feedback"
    assert record["user_feedback"] == "liked"


@pytest.mark.parametrize(
    "pattern,liked,error",
    [
        ("", True, ValueError),
        ("valid pattern", 1, TypeError),
    ],
)
def test_record_feedback_rejects_invalid_input(tmp_path, pattern, liked, error):
    loop = LearningLoop(tmp_path / "experiences.jsonl")
    with pytest.raises(error):
        loop.record_feedback(pattern, liked)
