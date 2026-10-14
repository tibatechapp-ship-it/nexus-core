"""Tests for council topics."""
import os
import sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from src.council.topics import (
    TOPICS, get_topic, list_categories, search_topics
)


def test_topics_count():
    """24 موضوع متوقع."""
    assert len(TOPICS) == 24


def test_get_topic_valid():
    """جلب موضوع صحيح."""
    t = get_topic("db_sqlite_vs_postgres")
    assert t is not None
    assert t.category == "database"
    assert "SQLite" in t.title


def test_get_topic_invalid():
    """جلب موضوع غير موجود."""
    assert get_topic("nonexistent") is None


def test_list_categories():
    """قائمة الفئات."""
    cats = list_categories()
    assert "database" in cats
    assert "framework" in cats
    assert "security" in cats
    assert "llm" in cats
    assert len(cats) >= 8


def test_search_by_category():
    """البحث بالفئة."""
    results = search_topics("database")
    assert len(results) >= 2


def test_search_by_title():
    """البحث بالعنوان."""
    results = search_topics("SQLite")
    assert len(results) >= 1
    assert any("SQLite" in r["title"] for r in results)


def test_high_risk_topics():
    """المواضيع عالية الخطورة معلَّمة."""
    security_topics = [
        t for t in TOPICS.values()
        if t.category == "security"
    ]
    assert len(security_topics) >= 3
    for t in security_topics:
        assert t.risk_level == "high"
