"""Tests for council history."""
import os
import sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from src.council.history import CouncilHistory


class FakeResult:
    verdict = "approve"
    score = 0.85
    rounds = 2
    security_events = []


@pytest.fixture
def hist(tmp_path, monkeypatch):
    h = CouncilHistory(history_dir=str(tmp_path / "hist"))
    # Disable RAG for tests
    h._rag = False
    monkeypatch.setattr(h, "_get_rag", lambda: None)
    return h


def test_history_empty(hist):
    stats = hist.stats()
    assert stats["total"] == 0


def test_history_save(hist):
    rec_id = hist.save(FakeResult(), topic_id="test_topic", category="test")
    assert rec_id is not None
    assert rec_id.startswith("decision_")


def test_history_stats(hist):
    hist.save(FakeResult(), topic_id="q1", category="cat")
    hist.save(FakeResult(), topic_id="q2", category="cat")

    stats = hist.stats()
    assert stats["total"] == 2
    assert stats["by_verdict"]["approve"] == 2


def test_history_list_recent(hist):
    hist.save(FakeResult(), topic_id="q1")
    hist.save(FakeResult(), topic_id="q2")

    recent = hist.list_recent(5)
    assert len(recent) == 2
