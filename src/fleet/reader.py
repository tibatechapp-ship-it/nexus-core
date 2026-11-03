"""Fleet Reader — قارئ لوحة الترتيب الحي (ب3.1 — v1.50.0).

يغلق الفجوة ف4: التوجيه لا يقرأ القياس. هذه الوحدة تقرأ
``reports/fleet_inventory.json`` **وقت التشغيل** وتعرض واجهة واحدة صادقة:

* ``load_scores()`` — قاموس الهوية ``(framework, name)`` ← ``FleetScore``.
  غياب التقرير أو فساده = ``{}`` معلن (بلا قياس لا توجيه بالدرجة) — لا
  انفجار ولا درجات مخترعة.
* ``rank_candidates()`` — المرشحون بالدرجة نازلاً ثم الاسم حتمياً؛
  المكسور (``status == "broken"``) يُستبعد من الفوز ويُدفع إلى الذيل.
* ``pick_best()`` — الأعلى درجة يفوز دائماً بين الأحياء؛ ``None`` إن
  لم يبقَ مرشح حي.

قراءة بحتة: لا كتابة، لا شبكة، ولا استيراد لوحدات الوكلاء.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

__all__ = ["FleetScore", "load_scores", "rank_candidates", "pick_best", "default_report_path"]

ROOT = Path(__file__).resolve().parents[2]


def default_report_path() -> Path:
    """مسار التقرير المعتمد — قابل للإعادة للاختبارات والبيئات."""
    return ROOT / "reports" / "fleet_inventory.json"


@dataclass(frozen=True)
class FleetScore:
    """درجة وكيل واحدة كما قرأها التقرير المعتمد وقت التشغيل."""

    name: str
    framework: str
    score: float
    tier: str
    status: str


def load_scores(path: Path | None = None) -> dict[tuple[str, str], FleetScore]:
    """اقرأ درجات الأسطول من التقرير المعتمد — غيابه ``{}`` معلن."""
    target = Path(path) if path is not None else default_report_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        rows = payload["ranking"]
        scores: dict[tuple[str, str], FleetScore] = {}
        for row in rows:
            scores[(str(row["framework"]), str(row["name"]))] = FleetScore(
                name=str(row["name"]),
                framework=str(row["framework"]),
                score=float(row.get("score", 0.0)),
                tier=str(row.get("tier", "C")),
                status=str(row.get("status", "broken")),
            )
        return scores
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {}  # معلن: بلا تقرير صالح لا توجيه بالدرجة


def rank_candidates(
    candidates: Iterable[tuple[str, str]],
    scores: dict[tuple[str, str], FleetScore] | None = None,
) -> list[tuple[str, str]]:
    """المرشحون بالدرجة نازلاً ثم الاسم — والمكسور آخراً لا أولاهما.

    المرشح بلا قياس يُعامل كأدنى درجة (0.0) عدلاً — بلا مجاملة صامتة.
    """
    live: list[tuple[float, str, tuple[str, str]]] = []
    broken: list[tuple[str, str]] = []
    for key in candidates:
        info = (scores or {}).get(key)
        if info is not None and info.status == "broken":
            broken.append(key)
            continue
        live.append((-(info.score if info else 0.0), key[1], key))
    live.sort(key=lambda t: (t[0], t[1]))
    return [key for _, _, key in live] + sorted(broken)


def pick_best(
    candidates: Iterable[tuple[str, str]],
    scores: dict[tuple[str, str], FleetScore] | None = None,
) -> tuple[str, str] | None:
    """الأعلى درجة يفوز بين الأحياء؛ ``None`` إن لم يبقَ حي."""
    ranked = rank_candidates(candidates, scores)
    if not ranked:
        return None
    best = ranked[0]
    info = (scores or {}).get(best)
    if info is not None and info.status == "broken":
        return None  # كل المرشحين مكسورون — لا فوز زوراً
    return best
