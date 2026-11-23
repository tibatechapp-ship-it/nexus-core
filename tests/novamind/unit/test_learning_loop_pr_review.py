import pytest

from novamind.core.learning_loop import LearningLoop


def test_pr_review_learning_records_allowlisted_metadata_only(tmp_path):
    loop = LearningLoop(tmp_path / 'experiences.jsonl')
    result = loop.learn_from_pr_review('owner/repo', 42, [
        {
            'filename': 'src/app.py',
            'category': 'security',
            'severity': 'high',
            'rule_id': 'unsafe-shell',
            'message': 'shell invocation needs validation',
            'source': 'PRIVATE SOURCE SHOULD NOT BE STORED',
            'patch': 'PRIVATE PATCH SHOULD NOT BE STORED',
            'api_key': 'SECRET SHOULD NOT BE STORED',
        }
    ])

    assert result['learned'] == 1
    experiences = loop.load_all()
    assert len(experiences) == 1
    exp = experiences[0]
    assert exp.agent == 'pr_reviewer'
    assert exp.task == 'PR review: owner/repo#42'
    assert exp.outcome == 'partial'
    assert exp.input_size > 0

    persisted = (tmp_path / 'experiences.jsonl').read_text(encoding='utf-8')
    assert 'PRIVATE SOURCE' not in persisted
    assert 'PRIVATE PATCH' not in persisted
    assert 'SECRET SHOULD NOT' not in persisted


def test_pr_review_learning_ignores_empty_or_unstructured_findings(tmp_path):
    loop = LearningLoop(tmp_path / 'experiences.jsonl')
    result = loop.learn_from_pr_review('owner/repo', 1, [None, {}, {'source': 'raw'}])
    assert result == {'learned': 0, 'experience_ids': []}
    assert loop.load_all() == []


@pytest.mark.parametrize('repo,pr_num,issues', [
    ('', 1, []),
    ('owner/repo', -1, []),
    ('owner/repo', True, []),
    ('owner/repo', 1, 'not-a-list'),
])
def test_pr_review_learning_validates_contract(tmp_path, repo, pr_num, issues):
    loop = LearningLoop(tmp_path / 'experiences.jsonl')
    with pytest.raises((ValueError, TypeError)):
        loop.learn_from_pr_review(repo, pr_num, issues)
