"""Tests for council cache."""
import os
import sys
import time
import tempfile
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from src.council.cache import CouncilCache


class FakeResult:
    verdict = "test_verdict"
    score = 0.75
    rounds = 2
    transcript = [
        {"member": "profiler", "response": "test1"},
        {"member": "analyst", "response": "test2"},
    ]


@pytest.fixture
def cache(tmp_path):
    """Cache مؤقت لكل اختبار."""
    return CouncilCache(cache_dir=str(tmp_path / "cache"), ttl=3600)


def test_cache_empty_on_start(cache):
    """Cache فارغ في البداية."""
    assert cache.get("test question") is None
    assert cache.stats()["total_entries"] == 0


def test_cache_set_and_get(cache):
    """حفظ واسترجاع."""
    result = FakeResult()
    q_hash = cache.set("test question", result)
    assert q_hash is not None

    cached = cache.get("test question")
    assert cached is not None
    assert cached.verdict == "test_verdict"
    assert cached.score == 0.75
    assert cached.rounds == 2


def test_cache_hits_increase(cache):
    """كل get يزيد hits."""
    cache.set("q", FakeResult())

    c1 = cache.get("q")
    assert c1.hits == 1

    c2 = cache.get("q")
    assert c2.hits == 2


def test_cache_normalization(cache):
    """التطبيع: علامات الترقيم والمسافات."""
    cache.set("هل نستخدم Redis؟", FakeResult())

    # نفس السؤال بصيغة مختلفة
    cached = cache.get("هل نستخدم Redis")
    assert cached is not None
    assert cached.verdict == "test_verdict"


def test_cache_expiry(tmp_path):
    """انتهاء الصلاحية."""
    cache = CouncilCache(cache_dir=str(tmp_path / "cache"), ttl=1)
    cache.set("q", FakeResult())

    # موجود فوراً
    assert cache.get("q") is not None

    # بعد انتهاء TTL
    time.sleep(2)
    assert cache.get("q") is None


def test_cache_clear(cache):
    """حذف الكل."""
    cache.set("q1", FakeResult())
    cache.set("q2", FakeResult())
    assert cache.stats()["total_entries"] == 2

    count = cache.clear()
    assert count == 2
    assert cache.stats()["total_entries"] == 0


def test_cache_stats(cache):
    """إحصائيات."""
    cache.set("q1", FakeResult())
    cache.set("q2", FakeResult())
    cache.get("q1")
    cache.get("q1")

    stats = cache.stats()
    assert stats["total_entries"] == 2
    assert stats["valid_entries"] == 2
    assert stats["total_hits"] == 2
