"""Council Cache — تخزين مؤقت للمداولات المتشابهة."""
from __future__ import annotations
import os
import sys
import json
import time
import hashlib
from dataclasses import dataclass, asdict
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))


@dataclass
class CachedVerdict:
    """نتيجة مداولة مخزّنة."""
    question_hash: str
    question: str
    verdict: str
    score: float
    rounds: int
    transcript_summary: str
    timestamp: float
    expires_at: float
    hits: int = 0


class CouncilCache:
    """Cache بسيط مع TTL + تطابق نصي."""

    DEFAULT_TTL = 86400  # 24 ساعة
    SIMILARITY_THRESHOLD = 0.92  # 92% تشابه

    def __init__(self, cache_dir: str = None, ttl: int = None):
        self.cache_dir = cache_dir or os.path.expanduser("~/.nexus/data/council_cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.ttl = ttl or self.DEFAULT_TTL
        self._index = None

    def _hash_question(self, question: str) -> str:
        """يحوّل السؤال لمفتاح."""
        normalized = question.lower().strip()
        # إزالة علامات الترقيم
        for ch in "؟?.:!,،":
            normalized = normalized.replace(ch, "")
        # إزالة المسافات الزائدة
        normalized = " ".join(normalized.split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    def _path(self, q_hash: str) -> str:
        return os.path.join(self.cache_dir, f"{q_hash}.json")

    def get(self, question: str) -> Optional[CachedVerdict]:
        """يجلب من الكاش إذا موجود وطازج."""
        q_hash = self._hash_question(question)
        path = self._path(q_hash)

        if not os.path.exists(path):
            return None

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            cached = CachedVerdict(**data)

            # فحص انتهاء الصلاحية
            if time.time() > cached.expires_at:
                os.remove(path)
                return None

            # تحديث عدد الإصابات
            cached.hits += 1
            with open(path, "w", encoding="utf-8") as f:
                json.dump(asdict(cached), f, ensure_ascii=False, indent=2)

            return cached
        except Exception:
            return None

    def set(self, question: str, result) -> str:
        """يخزّن نتيجة مداولة."""
        q_hash = self._hash_question(question)

        # ملخص الحوار
        summary = ""
        try:
            parts = []
            for e in result.transcript[:6]:
                resp = e.get("response", "")[:150]
                parts.append(f"[{e['member']}]: {resp}")
            summary = " | ".join(parts)
        except Exception:
            pass

        cached = CachedVerdict(
            question_hash=q_hash,
            question=question,
            verdict=result.verdict,
            score=result.score,
            rounds=result.rounds,
            transcript_summary=summary,
            timestamp=time.time(),
            expires_at=time.time() + self.ttl,
        )

        with open(self._path(q_hash), "w", encoding="utf-8") as f:
            json.dump(asdict(cached), f, ensure_ascii=False, indent=2)

        return q_hash

    def clear(self) -> int:
        """يحذف كل الكاش."""
        count = 0
        for fname in os.listdir(self.cache_dir):
            if fname.endswith(".json"):
                os.remove(os.path.join(self.cache_dir, fname))
                count += 1
        return count

    def stats(self) -> dict:
        """إحصائيات الكاش."""
        files = [f for f in os.listdir(self.cache_dir) if f.endswith(".json")]
        total_hits = 0
        valid = 0
        expired = 0
        now = time.time()

        for fname in files:
            try:
                with open(os.path.join(self.cache_dir, fname), encoding="utf-8") as f:
                    data = json.load(f)
                total_hits += data.get("hits", 0)
                if now > data.get("expires_at", 0):
                    expired += 1
                else:
                    valid += 1
            except Exception:
                pass

        return {
            "total_entries": len(files),
            "valid_entries": valid,
            "expired_entries": expired,
            "total_hits": total_hits,
            "ttl_hours": self.ttl / 3600,
        }


# Singleton
_cache = None

def get_cache() -> CouncilCache:
    global _cache
    if _cache is None:
        _cache = CouncilCache()
    return _cache
