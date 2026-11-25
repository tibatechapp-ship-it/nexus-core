"""فهرس الذكاء — تهذيب → تقطيع → تضمين محلي → استرجاع بميزانية توكن.

الهدف المعلن: الوكيل يستدعي ``retrieve`` بدل تمرير سياق ضخم — فيحصل
على **شرائح + استشهادات** فقط داخل ميزانية توكن معلنة، مع فلترة
صلاحيات (ACL) قبل أي حساب.

المراحل الأربع:

1. ``sanitize``   — حذف الأسرار وبيانات الهوية قبل أي تخزين أو إرسال؛
   كل نمط يُستبدل بوسم ``[REDACTED:<kind>]`` ويُعدّ في تقرير التهذيب.
2. ``chunk``      — شرائح 300–800 كلمة (تقريب توكن) مع حدود فقرية.
3. ``embed``      — تضمين محلي حتمي (حقيبة كلمات مبعثرة بـ SHA-1 مع
   تطبيع L2) — بلا شبكة وبلا اعتماديات، ومطابق لكل تشغيل.
4. ``retrieve``   — ترتيب جيبي التشابه، تغليف جشع داخل الميزانية،
   استشهادات صريحة، وذاكرة مؤقتة TTL للاستعلامات المتكررة.

الحد الصادق: هذا تضمين معجمي لا عصبي — دقة أقل من نماذج التضمين،
لكن صفر تكلفة وصفر شبكة وتحديد تام؛ النماذج العصبية خطّاف لاحق
بلا تغيير في العقود.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.ops.contracts import stable_id
from src.ops.store import OpsStore

__all__ = [
    "SECRET_PATTERNS",
    "Chunk",
    "IndexConfig",
    "sanitize",
    "chunk_text",
    "embed",
    "cosine",
    "OpsIndex",
]

#: أنماط الأسرار وبيانات الهوية — (النمط، نوع الوسم) بالترتيب الأولوي.
SECRET_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"sk-[A-Za-z0-9_-]{16,}", "api_key"),
    (r"ghp_[A-Za-z0-9]{20,}", "github_token"),
    (r"AKIA[0-9A-Z]{12,}", "aws_key"),
    (r"xox[bap]-[A-Za-z0-9-]{10,}", "slack_token"),
    (r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "jwt"),
    (
        r"(?i)\b(password|passwd|pass|pwd|secret|token|api[_-]?key|"
        r"access[_-]?key)\s*[=:]\s*\S+",
        "inline_secret",
    ),
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "email"),
    (r"(?<!\w)\+?\d{7,12}(?!\w)", "phone"),
)

#: التعبيرات المجمّعة مرة واحدة — لا إعادة تجميع في كل استدعاء.
_COMPILED: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), kind) for pattern, kind in SECRET_PATTERNS
)

#: حد الجلب الخام من ملف واحد — سقف حماية من الملفات الضخمة.
MAX_INGEST_BYTES = 2_000_000


@dataclass(frozen=True)
class Chunk:
    """شريحة نصية واحدة — نصها وعدد توكنها (تقريب الكلمات) وترتيبها."""

    index: int
    text: str
    tokens: int


@dataclass(frozen=True)
class IndexConfig:
    """إعدادات الفهرس — أبعاد التضمين وحدود التقطيع والميزانية."""

    dims: int = 256
    chunk_target: int = 800
    chunk_min: int = 300
    budget_tokens: int = 1500
    top_k: int = 5
    cache_size: int = 128
    cache_ttl_seconds: int = 600

    def __post_init__(self) -> None:
        if self.dims < 16:
            raise ValueError("أبعاد التضمين لا تقل عن 16")
        if not 1 <= self.chunk_min <= self.chunk_target:
            raise ValueError("حدود التقطيع غير مرتبة: 1 ≤ min ≤ target")
        if self.budget_tokens < 1 or self.top_k < 1:
            raise ValueError("الميزانية وTop-K لا يقلان عن 1")
        if self.cache_size < 0 or self.cache_ttl_seconds < 1:
            raise ValueError("إعدادات الذاكرة المؤقتة غير سليمة")


def sanitize(text: str) -> tuple[str, dict[str, int]]:
    """تهذيب نص واحد — استبدال كل مطابقة بوسمها وإرجاع عدّ الأنماط.

    التهذيب **قبل** التخزين والتضمين: لا سر يدخل الفهرس ولا استرجاع،
    والعدّ المعاد هو الدليل الملوحي في تقرير الإدخال.
    """
    removed: dict[str, int] = {}
    cleaned = text
    for pattern, kind in _COMPILED:
        cleaned, n = pattern.subn(f"[REDACTED:{kind}]", cleaned)
        if n:
            removed[kind] = removed.get(kind, 0) + n
    return cleaned, removed


def chunk_text(text: str, target: int = 800, min_tokens: int = 300) -> list[Chunk]:
    """تقطيع نص إلى شرائح — تغليف فقري حتى الهدف، وقسمة جمل للفقرات الضخمة.

    ``min_tokens`` سقف أدنى للشريحة الأخيرة: شريحة أضعف من ذلك تُدمج
    مع سابقتها بدل ترك قصاصة بلا سياق.
    """
    if target < 1:
        raise ValueError("هدف التقطيع لا يقل عن 1")
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []
    pieces: list[str] = []
    for para in paragraphs:
        if _tokens_of(para) <= target:
            pieces.append(para)
            continue
        sentences = re.split(r"(?<=[.!?؟。])\s+", para)
        buf = ""
        for sentence in sentences:
            if buf and _tokens_of(buf) + _tokens_of(sentence) > target:
                pieces.append(buf)
                buf = sentence
            else:
                buf = f"{buf} {sentence}".strip()
        if buf:
            pieces.append(buf)
    chunks: list[Chunk] = []
    buf = ""
    for piece in pieces:
        if buf and _tokens_of(buf) + _tokens_of(piece) > target:
            chunks.append(Chunk(len(chunks), buf, _tokens_of(buf)))
            buf = piece
        else:
            buf = f"{buf}\n\n{piece}".strip()
    if buf:
        if chunks and _tokens_of(buf) < min_tokens:
            merged = f"{chunks[-1].text}\n\n{buf}"
            chunks[-1] = Chunk(chunks[-1].index, merged, _tokens_of(merged))
        else:
            chunks.append(Chunk(len(chunks), buf, _tokens_of(buf)))
    return chunks


def _tokens_of(text: str) -> int:
    """عدد التوكن التقريبي — الكلمات؛ الدينار الواحد كلمة واحدة هنا."""
    return len(text.split())


def embed(text: str, dims: int = 256) -> tuple[float, ...]:
    """تضمين حتمي محلي — حقيبة كلمات مبعثرة على SHA-1 مع تطبيع L2.

    نفس النص يعطي نفس المتجه في كل تشغيل وكل جهاز — أساس الاختبار
    والاسترجاع المثبت. النص الفارغ متجه صفري مشطوف بـ 1.0 لتفادي
    القسمة على صفر (لا يطابق شيئًا عمليًا).
    """
    if dims < 1:
        raise ValueError("الأبعاد لا تقل عن 1")
    vec = [0.0] * dims
    for word in re.findall(r"[\w]+", text.lower()):
        idx = int(hashlib.sha1(word.encode("utf-8"), usedforsecurity=False).hexdigest(), 16) % dims
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return tuple(round(v / norm, 6) for v in vec)


def cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """تشابه جيبي — المتجهات مطبّعة مسبقًا فالحاصل جداء نقدي مقصوص."""
    n = min(len(a), len(b))
    dot = sum(x * y for x, y in zip(a[:n], b[:n]))
    return round(max(0.0, min(1.0, dot)), 6)


def _vec_to_json(vec: tuple[float, ...]) -> str:
    """تسلسل المتجه إلى عمود JSON — مضغوط بلا فراغات."""
    return json.dumps(list(vec), separators=(",", ":"))


def _vec_from_json(text: str) -> tuple[float, ...]:
    """فك تسلسل المتجه — القوائم المشوّهة ترفع خطأ صريحًا."""
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("متجه مخزّن مشوّه")
    return tuple(float(v) for v in data)


class OpsIndex:
    """الفهرس الموحّد — إدخال مُهذَّب، استرجاع ميزانية بوضع ACL، ذاكرة TTL."""

    def __init__(self, store: OpsStore, config: IndexConfig | None = None) -> None:
        self._store = store
        self._config = config or IndexConfig()
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    # ── الإدخال ───────────────────────────────────────────────────────────

    def ingest_text(self, text: str, doc_id: str, title: str = "",
                    acl: str = "team:all", version: str = "v1",
                    ttl_days: int = 0) -> dict[str, Any]:
        """إدخال نص واحد: تهذيب ← تقطيع ← تضمين ← تخزين في القاعدة الواحدة.

        إعادة إدخال نفس ``doc_id`` باستبدال شرائحه (إصدار جديد) —
        الفهرس يعكس آخر نسخة لا تراكم النسخ.
        """
        if not doc_id.strip():
            raise ValueError("doc_id يجب أن يكون نصًا غير فارغ")
        if not acl.strip():
            raise ValueError("acl يجب أن يكون نصًا غير فارغ")
        if ttl_days < 0:
            raise ValueError("ttl_days لا يكون سالبًا")
        cleaned, removed = sanitize(text)
        chunks = chunk_text(cleaned, self._config.chunk_target, self._config.chunk_min)
        self._store.audit("index.ingest", doc_id,
                          {"slices": len(chunks), "removed": removed, "acl": acl})
        with self._store._conn:
            self._store._conn.execute("DELETE FROM slices WHERE doc_id = ?", (doc_id,))
            for ch in chunks:
                vec = embed(ch.text, self._config.dims)
                self._store._conn.execute(
                    "INSERT INTO slices (id, doc_id, title, acl, body, tokens, "
                    "version, ttl_days, vec, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        stable_id(doc_id, str(ch.index)), doc_id, title, acl,
                        ch.text, ch.tokens, version, ttl_days,
                        _vec_to_json(vec), self._store_now(),
                    ),
                )
        self._invalidate_cache()
        return {"doc_id": doc_id, "slices": len(chunks),
                "tokens": sum(c.tokens for c in chunks), "removed": removed}

    def ingest_file(self, path: str | Path, doc_id: str | None = None,
                    title: str = "", acl: str = "team:all",
                    version: str = "v1", ttl_days: int = 0) -> dict[str, Any]:
        """إدخال ملف نصي — سقف الحجم معلن، والملفات المشوّهة خطأ صريح."""
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"ملف الإدخال غير موجود: {p}")
        if p.stat().st_size > MAX_INGEST_BYTES:
            raise ValueError(
                f"الملف يتجاوز سقف الإدخال {MAX_INGEST_BYTES} بايت: {p}"
            )
        text = p.read_text(encoding="utf-8", errors="replace")
        return self.ingest_text(
            text, doc_id or p.name, title or p.name, acl, version, ttl_days
        )

    # ── الاسترجاع ─────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int | None = None,
               acl: str | None = None) -> list[dict[str, Any]]:
        """ترتيب الشرائح جيبي التشابه — فلتر الصلاحيات قبل أي حساب."""
        k = self._config.top_k if top_k is None else top_k
        qvec = embed(query, self._config.dims)
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in self._store._conn.execute(
            "SELECT id, doc_id, title, acl, body, tokens, vec FROM slices"
        ):
            if acl is not None and not self._acl_allows(acl, row["acl"]):
                continue
            score = cosine(qvec, _vec_from_json(row["vec"]))
            scored.append((score, {
                "id": row["id"], "doc_id": row["doc_id"], "title": row["title"],
                "acl": row["acl"], "text": row["body"], "tokens": row["tokens"],
                "score": score,
            }))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
        return [item for _, item in scored[:k]]

    def retrieve(self, query: str, budget_tokens: int | None = None,
                 top_k: int | None = None, acl: str = "team:all") -> dict[str, Any]:
        """الواجهة الرسمية للوكيل — شرائح داخل الميزانية + استشهادات صريحة.

        التغليف جشع بالترتيب: أعلى تشابه أولًا، وأول شريحة تتجاوز
        الميزانية تُوقف التغليف. الاستعلام المتكرر يعاد من ذاكرة TTL
        بلا حساب ثانٍ.
        """
        budget = (self._config.budget_tokens if budget_tokens is None
                  else budget_tokens)
        if budget < 1:
            raise ValueError("الميزانية لا تقل عن 1")
        cached = self._cache_get(query, budget, acl)
        if cached is not None:
            return cached
        selected: list[dict[str, Any]] = []
        used = 0
        for item in self.search(query, top_k=top_k, acl=acl):
            if used + item["tokens"] > budget:
                break
            selected.append(item)
            used += item["tokens"]
        result: dict[str, Any] = {
            "slices": selected,
            "tokens_used": used,
            "citations": [s["id"] for s in selected],
        }
        self._cache_put(query, budget, acl, result)
        return result

    # ── الصلاحيات والصلاحية الزمنية ───────────────────────────────────────

    def _acl_allows(self, requested: str, granted: str) -> bool:
        """فلتر صلاحيات صريح — ``team:*`` wildcard للفريق، والعام للجميع."""
        if granted == "team:all":
            return True
        if requested == granted:
            return True
        if requested.endswith(":*"):
            prefix = requested[:-1]
            return granted.startswith(prefix)
        return False

    def prune_expired(self) -> int:
        """حذف الشرائح المنتهية (ttl_days > 0) — يعيد عدد ما حُذف."""
        rows = self._store._conn.execute(
            "SELECT id, created_at, ttl_days FROM slices WHERE ttl_days > 0"
        ).fetchall()
        now = time.time()
        stale: list[str] = []
        for r in rows:
            created = self._parse_ts(r["created_at"])
            if created is not None and (now - created) > r["ttl_days"] * 86400:
                stale.append(r["id"])
        with self._store._conn:
            for sid in stale:
                self._store._conn.execute("DELETE FROM slices WHERE id = ?", (sid,))
        if stale:
            self._store.audit("index.prune", f"{len(stale)} slices", {})
            self._invalidate_cache()
        return len(stale)

    # ── الذاكرة المؤقتة ───────────────────────────────────────────────────

    def _cache_key(self, query: str, budget: int, acl: str) -> str:
        """مفتاح ذاكرة موحّد — الاستعلام والميزانية والصلاحية معًا."""
        return f"{query}\x1f{budget}\x1f{acl}"

    def _cache_get(self, query: str, budget: int, acl: str) -> dict[str, Any] | None:
        """إرجاع من الذاكرة إن كانت حية — المنتهي يُحذف بالمرور."""
        key = self._cache_key(query, budget, acl)
        entry = self._cache.get(key)
        if entry is None:
            return None
        stored_at, payload = entry
        if time.time() - stored_at > self._config.cache_ttl_seconds:
            del self._cache[key]
            return None
        return payload

    def _cache_put(self, query: str, budget: int, acl: str,
                   payload: dict[str, Any]) -> None:
        """تخزين نتيجة في الذاكرة — الطرد يطرد الأقدم إدخالًا."""
        if self._config.cache_size == 0:
            return
        while len(self._cache) >= self._config.cache_size:
            oldest = min(self._cache.items(), key=lambda kv: kv[1][0])[0]
            del self._cache[oldest]
        self._cache[self._cache_key(query, budget, acl)] = (time.time(), payload)

    def _invalidate_cache(self) -> None:
        """إبطال الذاكرة بعد أي إدخال أو حذف — الصحة قبل السرعة."""
        self._cache.clear()

    # ── أدوات الوقت ───────────────────────────────────────────────────────

    def _store_now(self) -> str:
        """زمن الإدخال — منزوع من العقود لتسهيل اختبار التقادم."""
        from src.ops.contracts import now_iso
        return now_iso()

    def _parse_ts(self, value: str) -> float | None:
        """تحليل طابع زمني ISO — الفاسد يعود ``None`` لا استثناء."""
        from datetime import datetime
        try:
            return datetime.fromisoformat(value).timestamp()
        except (ValueError, TypeError):
            return None
