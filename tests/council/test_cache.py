"""Tests for council cache."""
import os
import sys
import time
import tempfile
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from src.council.cache import CouncilCache, CACHE_VERSION


class FakeResult:
    verdict = "test_verdict"
    score = 0.75
    rounds = 2
    transcript = [
        {"member": "profiler", "response": "test1"},
        {"member": "analyst", "response": "test2"},
    ]


class FakeResultConsensus(FakeResult):
    consensus = True


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


# ═══ v1.9.2 — full transcript + consensus + cache versioning ═══

def test_cache_persists_full_transcript(cache):
    """الـ transcript الكامل يُحفظ ويُسترجع كما هو (البند ①②)."""
    result = FakeResultConsensus()
    cache.set("q full", result)

    cached = cache.get("q full")
    assert cached is not None
    assert cached.transcript == result.transcript
    assert cached.consensus is True


def test_cache_missing_consensus_stays_none(cache):
    """نتيجة بلا حقل consensus → يُخزّن None (ليُستخدم fallback score)."""
    cache.set("q none", FakeResult())
    cached = cache.get("q none")
    assert cached is not None
    assert cached.consensus is None


def test_cache_stores_version(cache):
    """كل إدخال جديد يحمل نسخة الكاش الحالية."""
    cache.set("q ver", FakeResult())
    cached = cache.get("q ver")
    assert cached is not None
    assert cached.cache_version == CACHE_VERSION
    assert cache.stats()["cache_version"] == CACHE_VERSION


def test_cache_stale_version_ignored(tmp_path):
    """إدخال بنسخة قديمة (أو بلا حقل نسخة) يُتجاهل عند القراءة (البند ⑤)."""
    import json
    cache = CouncilCache(cache_dir=str(tmp_path / "cache"), ttl=3600)
    # اكتب إدخالاً "قديماً" يدوياً بلا cache_version
    q_hash = cache._hash_question("q stale")
    with open(cache._path(q_hash), "w", encoding="utf-8") as f:
        json.dump({
            "question_hash": q_hash, "question": "q stale",
            "verdict": "old", "score": 0.5, "rounds": 1,
            "transcript_summary": "", "timestamp": 0.0,
            "expires_at": time.time() + 3600, "hits": 0,
        }, f, ensure_ascii=False)

    assert cache.get("q stale") is None
    assert cache.stats()["stale_entries"] == 1


def test_cache_stats_valid_after_set(cache):
    """الإدخال الجديد يُعدّ صالحاً (لا قديماً) في الإحصائيات."""
    cache.set("q valid", FakeResult())
    stats = cache.stats()
    assert stats["valid_entries"] == 1
    assert stats["stale_entries"] == 0
