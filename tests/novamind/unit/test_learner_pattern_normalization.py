from novamind.agents.learner import LearnerAgent


def test_pattern_normalization_preserves_words_and_collapses_whitespace():
    agent = LearnerAgent()

    assert agent._normalize_pattern("Concurrent pattern") == "concurrent pattern"
    assert agent._normalize_pattern("line 42: Concurrent-pattern!") == "line concurrentpattern"
