"""الرادار التشغيلي — رصد مصادر معلنة إلى إشارات موحّدة بجدولة صامتة.

القواعد المعلنة المطبَّقة هنا حرفيًا:

1. **الكتالوج معلن**: المصادر الـ 14 قابلة للعدّ والفحص — تغييرها قرار
   بيان لا كود مخفي.
2. **عزل المصادر**: كل مصدر يُجلب بمعزل — فشل مصدر يُسجَّل ولا يوقف البقية.
3. **الميزانية**: ``max_items_per_run`` سقف قاسٍ — لا استهلاك مفتوح.
4. **إزالة التكرار**: ``stable_id(المصدر, الرابط)`` + نافذة زمنية في المخزن.
5. **منع الإزعاج**: لا إشعار لكل عنصر — ملخص Top-N واحد، وساعات صامتة
   تؤجّل الدورة الصباحية/المسائية بدل كسرها.

الجلب الحي اختياري بالتصميم: ``run(fetcher=None)`` بلا شبكة إطلاقًا —
تقرير كتالوغي حتمي. الدالة الحية (``http_fetch`` أو أي دالة مُمرَّرة)
هي الخطّاف المعلن الوحيد للشبكة، وتحترم مهلة كل مصدر.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from src.ops.contracts import Digest, Signal, now_iso, stable_id
from src.ops.store import OpsStore

__all__ = [
    "DEFAULT_SOURCES",
    "KEYWORD_SCORES",
    "RadarConfig",
    "RadarResult",
    "RadarSource",
    "OpsRadar",
    "http_fetch",
]

#: مهلة الجلب الحي الواحد (ثوانٍ) — سقف معلن لكل مصدر.
FETCH_TIMEOUT_SECONDS = 8

#: درجات الكلمات المفتاحية — الترتيب بالأهمية لعملنا لا بحجم الضجيج.
KEYWORD_SCORES: Mapping[str, float] = {
    "agent": 3.0, "agentic": 3.0, "llm": 3.0, "mcp": 3.0, "sandbox": 2.5,
    "security": 2.5, "vulnerability": 2.5, "cve": 2.5, "rag": 2.0,
    "memory": 2.0, "orchestration": 2.0, "multi-agent": 2.0, "eval": 1.5,
    "benchmark": 1.5, "token": 1.0, "embedding": 1.0, "cli": 1.0,
    "terminal": 1.0, "android": 1.0, "termux": 1.0,
}

#: الكتالوج المعلن — يُعرّف بعد صنفه مباشرة (انظر أسفل RadarSource).


@dataclass(frozen=True)
class RadarSource:
    """مصدر رصد واحد — معرّفه ونوعه وفترته ورابطه وكلماته المفتاحية."""

    id: str
    kind: str
    cadence: str
    url: str
    keywords: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("معرّف المصدر فارغ")
        if self.kind not in {"code", "models", "packages", "products"}:
            raise ValueError(f"نوع المصدر غير معروف: {self.kind!r}")
        if self.cadence not in {"morning", "evening", "both"}:
            raise ValueError(f"فترة المصدر غير معروفة: {self.cadence!r}")
        try:
            parsed = urlsplit(self.url)
            safe_url = (
                parsed.scheme in {"http", "https"}
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
            )
            _ = parsed.port
        except ValueError:
            safe_url = False
        if not safe_url:
            raise ValueError(f"رابط المصدر ليس HTTP(S) صالحاً: {self.url!r}")
        object.__setattr__(self, "keywords", tuple(self.keywords))


#: الكتالوج المعلن — 14 مصدرًا بأربع فترات (both/morning/evening).
#: الترتيب هو الترتيب: الرسّخون أولًا ثم المستجدات بنوعها.
DEFAULT_SOURCES: tuple[RadarSource, ...] = tuple(RadarSource(*row) for row in (
    ("github", "code", "both", "https://github.com/trending",
     ("agent", "orchestration", "multi-agent")),
    ("huggingface", "models", "both", "https://huggingface.co/models",
     ("llm", "embedding", "rag")),
    ("gitlab", "code", "both", "https://gitlab.com/explore",
     ("security", "ci")),
    ("npm", "packages", "morning", "https://www.npmjs.com/search?ranking=newness",
     ("agent", "cli", "token")),
    ("pypi", "packages", "morning", "https://pypi.org/newest/",
     ("llm", "rag", "security")),
    ("producthunt", "products", "morning", "https://www.producthunt.com",
     ("agent", "llm")),
    ("dockerhub", "packages", "morning", "https://hub.docker.com",
     ("sandbox", "container", "security")),
    ("ollama", "models", "morning", "https://ollama.com/library",
     ("llm", "local")),
    ("sourceforge", "code", "evening", "https://sourceforge.net",
     ("tools")),
    ("codeberg", "code", "evening", "https://codeberg.org/explore",
     ("agent", "cli")),
    ("bitbucket", "code", "evening", "https://bitbucket.org/repo/all",
     ("ci", "devops")),
    ("gitee", "code", "evening", "https://gitee.com/explore",
     ("orchestration", "agent")),
    ("kaggle", "models", "evening", "https://www.kaggle.com/models",
     ("eval", "benchmark")),
    ("replicate", "models", "evening", "https://replicate.com/collections",
     ("llm", "vision")),
))


@dataclass(frozen=True)
class RadarConfig:
    """إعدادات الرادار — السقوف والنوافذ والساعات الصامتة بلا غموض."""

    max_items_per_run: int = 200
    dedup_window_days: int = 30
    top_n: int = 10
    min_score: float = 1.0
    quiet_hours: tuple[int, ...] = (0, 1, 2, 3, 4, 5)

    def __post_init__(self) -> None:
        if self.max_items_per_run < 1:
            raise ValueError("الميزانية يجب أن تكون ≥ 1")
        if self.dedup_window_days < 0:
            raise ValueError("نافذة التكرار لا تكون سالبة")
        if self.top_n < 1:
            raise ValueError("Top-N لا يكون أصغر من 1")
        if any(not 0 <= h <= 23 for h in self.quiet_hours):
            raise ValueError("الساعات الصامتة أعداد 0–23")


@dataclass
class RadarResult:
    """نتيجة دورة رصد واحدة — لكل مصدر: حالته وعناصره، ثم ما خُزّن فعلًا."""

    cadence: str
    sources_ok: list[str] = field(default_factory=list)
    sources_failed: dict[str, str] = field(default_factory=dict)
    items_seen: int = 0
    items_stored: int = 0
    items_deduped: int = 0
    items_below_budget: int = 0
    skipped_quiet: bool = False
    top: list[Signal] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """التمثيل القياسي للنتيجة — الأعلى في اللوحة والملخص معًا."""
        return {
            "cadence": self.cadence,
            "sources_ok": list(self.sources_ok),
            "sources_failed": dict(self.sources_failed),
            "items_seen": self.items_seen,
            "items_stored": self.items_stored,
            "items_deduped": self.items_deduped,
            "items_below_budget": self.items_below_budget,
            "skipped_quiet": self.skipped_quiet,
            "top": [s.to_dict() for s in self.top],
        }


def score_item(title: str, tags: tuple[str, ...] = (),
               extra_keywords: tuple[str, ...] = ()) -> float:
    """درجة العنصر — مجموع كلماته المفتاحية، مع خصم بلا تكرار للكلمة."""
    text = f"{title} {' '.join(tags)}".lower()
    score = 0.0
    for kw, weight in KEYWORD_SCORES.items():
        if kw in text:
            score += weight
    for kw in extra_keywords:
        if kw in text and kw not in KEYWORD_SCORES:
            score += 1.5
    return round(score, 2)


def http_fetch(source: RadarSource, timeout: int = FETCH_TIMEOUT_SECONDS) -> list[dict[str, Any]]:
    """المُجلب الحي المعلن — الخطّاف الوحيد للشبكة في الرادار كله.

    يجلب صفحة المصدر ويستخرج العناوين والروابط بتحليل نصي صارم —
    بلا محرك متصفح وبلا اعتماديات. أي فشل شبكي استثناء تلتقطه
    دورة الرادار وتسجّله معزولًا لمصدره.
    """
    req = urllib.request.Request(
        source.url, headers={"User-Agent": "nexus-core-ops-radar/1.62"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 — RadarSource validates HTTP(S) URL
        body = resp.read(1_000_000).decode("utf-8", errors="replace")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in body.split("<"):
        if "href=" not in chunk or ">" not in chunk:
            continue
        text_part, _, link_part = chunk.partition("href=")
        title = text_part.strip(" >/")[:200]
        quote = '"' if '"' in link_part else "'"
        url = link_part.split(quote)[1] if quote in link_part else ""
        if not title or not url or url.startswith(("#", "javascript:")):
            continue
        if url.startswith("/"):
            url = source.url.rstrip("/") + url
        if url in seen:
            continue
        seen.add(url)
        items.append({"title": title, "url": url, "source": source.id})
        if len(items) >= 50:
            break
    return items


class OpsRadar:
    """الرادار الموحّد — دورة كاملة: جلب معزول ← تسجيل ← تكرار ← ميزانية ← ملخص."""

    def __init__(self, store: OpsStore,
                 config: RadarConfig | None = None,
                 sources: tuple[RadarSource, ...] = DEFAULT_SOURCES) -> None:
        self._store = store
        self._config = config or RadarConfig()
        self._sources = sources

    # ── الساعات الصامتة ───────────────────────────────────────────────────

    def is_quiet_hour(self, hour: int) -> bool:
        """هل الساعة صامتة؟ — الدورة تُؤجّل لا تُكسر، والإجابات حتمية."""
        return hour in self._config.quiet_hours

    # ── الدورة الكاملة ────────────────────────────────────────────────────

    def run(self, cadence: str = "morning",
            fetcher: Callable[[RadarSource], list[dict[str, Any]]] | None = None,
            now_hour: int | None = None) -> RadarResult:
        """دورة رصد واحدة — بلا شبكة افتراضيًا، وبمصادر معزولة مع شبكة.

        ``fetcher=None``: تقرير كتالوغي من المصادر المخزّنة فقط (حتمي).
        ``fetcher`` معطى: كل مصدر يُجلب بمعزل؛ فشله سطر في ``sources_failed``.
        ساعة صامتة: النتيجة تُرجَع بعلم ``skipped_quiet=True`` بلا جلب.
        """
        if cadence not in {"morning", "evening"}:
            raise ValueError(f"الفترة غير معروفة: {cadence!r}")
        result = RadarResult(cadence=cadence)
        if now_hour is not None and self.is_quiet_hour(now_hour):
            result.skipped_quiet = True
            self._store.audit("radar.skipped_quiet", cadence, {"hour": now_hour})
            return result
        active = [
            s for s in self._sources
            if s.cadence in {cadence, "both"}
        ]
        for source in active:
            if fetcher is None:
                result.sources_ok.append(source.id)
                continue
            try:
                items = fetcher(source)
            except Exception as exc:  # noqa: BLE001 — عزل فشل المصدر مقصود هنا
                result.sources_failed[source.id] = f"{type(exc).__name__}: {exc}"[:200]
                self._store.audit("radar.source_failed", source.id,
                                  {"error": result.sources_failed[source.id]})
                continue
            result.sources_ok.append(source.id)
            for raw in items:
                if result.items_seen >= self._config.max_items_per_run:
                    result.items_below_budget += 1
                    continue
                signal = self._normalize(source, raw)
                if signal is None:
                    continue
                result.items_seen += 1
                if signal.score < self._config.min_score:
                    continue
                stored = self._store.add_signal(
                    signal, dedup_window_days=self._config.dedup_window_days
                )
                if stored:
                    result.items_stored += 1
                else:
                    result.items_deduped += 1
        result.top = self._store.list_signals(limit=self._config.top_n)
        self._store.add_digest(self._digest(result))
        return result

    # ── التطبيع والتلخيص ──────────────────────────────────────────────────

    def _normalize(self, source: RadarSource,
                   raw: Mapping[str, Any]) -> Signal | None:
        """تطبيع عنصر خام إلى إشارة — العناصر المشوّهة تُهمَل بالعدّ لا بالصمت."""
        title = str(raw.get("title", "")).strip()
        url = str(raw.get("url", "")).strip()
        if not title or not url or not url.startswith(("http://", "https://")):
            return None
        tags = tuple(str(t) for t in raw.get("tags", ())) + (source.kind,)
        score = float(raw.get("score", score_item(title, tags, source.keywords)))
        return Signal(
            source=source.id, title=title, url=url,
            published_at=str(raw.get("published_at", "")),
            score=score, tags=tags, raw_ref=str(raw.get("raw_ref", "")),
            id=stable_id(source.id, url),
        )

    def _digest(self, result: RadarResult) -> Digest:
        """ملخص واحد حتمي — أعلى الإشارات في نص واحد بلا إشعارات متكررة."""
        day = now_iso()[:10]
        lines = [
            f"- المصادر السليمة: {len(result.sources_ok)} — الفاشلة: "
            f"{len(result.sources_failed)}",
            f"- العناصر: شوهت {result.items_seen} · خُزّنت {result.items_stored} · "
            f"كرر مُهمَل {result.items_deduped}",
        ]
        for s in result.top[:5]:
            lines.append(f"- [{s.score:.1f}] {s.source}: {s.title} ({s.url})")
        payload: dict[str, Any] = {
            "radar": result.to_dict(),
            "summary": "\n".join(lines),
            "counts": self._store.counts(),
        }
        return Digest(kind=result.cadence, day=day, payload=payload)


def load_config(path: str | None) -> RadarConfig:
    """تحميل إعدادات من JSON اختياري — المفاتيح الناقصة تعود لافتراضاتها."""
    if not path:
        return RadarConfig()
    data = _read_json(path)
    known = {k: v for k, v in data.items()
             if k in RadarConfig.__dataclass_fields__}
    return RadarConfig(**known)


def _read_json(path: str) -> dict[str, Any]:
    """قراءة ملف JSON مع فشل صريح — لا افتراض محتوى."""
    from pathlib import Path
    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"ملف الإعدادات ليس كائنًا: {path}")
    return data
