"""رادار التوليد — تقرير الصباح والمساء لمصادر الكود والنماذج والأدوات.

المبدأ المعلن: **كتالوج معلن وتقرير حتمي** — مصادر الرصد قابلة للعدّ والفحص،
والتقرير يُبنى بلا شبكة وبلا مفاجآت: نفس المدخلات تعطي نفس المخرجات حرفياً.

* **الفترتان**: «صباح» (ما يُقرأ عند بدء اليوم: المكتبات الجديدة والمنتجات
  الطازجة والمشاريع الصاعدة) و«مساء» (ما يُراجع عند الإغلاق: الأدوات الناضجة
  والنماذج الثقيلة ومستودعات الفرق).
* **الأنواع الأربعة**: ``code`` مستودعات ومشاريع · ``models`` نماذج ذكاء ·
  ``packages`` مكتبات وصور تشغيل · ``products`` منتجات وتطبيقات.
* **الاستفادة المعلنة**: كل مصدر يحمل سطر «المستفاد» الذي يشرح ماذا يضيف
  للأسطول عملياً — بلا تسويق.

الجلب الحي اختياري ومعزول: ``live_digest`` يقبل دالة جلب مُمرَّرة (قابلة
للاختبار)، وغيابها يعني تقريراً كتالوغياً خالصاً — لا شبكة افتراضياً
(تحترم ADR-0001 وADR-0004).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

__all__ = [
    "CADENCES", "KINDS", "RadarSource", "Radar",
    "DEFAULT_CATALOG", "LIVE_TIMEOUT_SECONDS",
]

#: الفترتان المدعومتان — خطأ الفترة رفع صريح لا تخمين.
CADENCES: tuple[str, ...] = ("morning", "evening")

#: أنواع المصادر — تُرتَّب بهذا الثبات في كل تقرير.
KINDS: tuple[str, ...] = ("code", "models", "packages", "products")

#: مهلة الجلب الحي الواحد (ثوانٍ) — لا تُرفع بلا قرار.
LIVE_TIMEOUT_SECONDS = 8


@dataclass(frozen=True)
class RadarSource:
    """مصدر رصد واحد: اسمه ونوعه وفترته ورابطه وما يُستفاد منه."""

    name: str
    label: str
    kind: str
    cadence: str
    url: str
    benefit: str

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"kind غير معروف: {self.kind} (المعروف: {KINDS})")
        if self.cadence not in CADENCES and self.cadence != "both":
            raise ValueError(f"cadence غير معروف: {self.cadence}")


#: الكتالوج الافتراضي — مُعلن هنا وحده؛ تغييره تغيير بيان لا تغيير كود.
#: الترتيب هو الترتيب: الرسّخون الثلاثة أولًا ثم المستجدات بنوعها.
DEFAULT_CATALOG: tuple[RadarSource, ...] = (
    RadarSource("github", "GitHub Trending", "code", "both",
                "https://github.com/trending",
                "المشاريع الأسرع نمواً اليوم — مرشّحان لفهم الأنماط الصاعدة"),
    RadarSource("huggingface", "Hugging Face", "models", "both",
                "https://huggingface.co/models",
                "النماذج المفتوحة الجديدة — مرشّحة للأدمغة المحلية والجسور"),
    RadarSource("gitlab", "GitLab Explore", "code", "both",
                "https://gitlab.com/explore",
                "مشاريع DevOps والمسارات المدمجة — منافس مباشر لما نبنيه"),
    RadarSource("npm", "npm New", "packages", "morning",
                "https://www.npmjs.com/search?ranking=newness",
                "مكتبات جافاسكربت الجديدة يومياً — مصدر أنماط الواجهة الحديثة"),
    RadarSource("pypi", "PyPI New", "packages", "morning",
                "https://pypi.org/newest/",
                "حزم بايثون الجديدة — أدوات تُجرّب وتُستفاد في الطبقات الحتمية"),
    RadarSource("producthunt", "Product Hunt", "products", "morning",
                "https://www.producthunt.com/leads/marketplaces",
                "المنتجات الجديدة كل صباح — إشارات طلب السوق قبل الكود"),
    RadarSource("kaggle", "Kaggle Models", "models", "morning",
                "https://www.kaggle.com/models",
                "نماذج ومسابقات وداتا — بيانات تدريب ومقاييس جاهزة للمقارنة"),
    RadarSource("ollama", "Ollama Library", "models", "morning",
                "https://ollama.com/library",
                "نماذج تشتغل على الجهاز — مرشّح الأدمغة المحلية فوراً"),
    RadarSource("codeberg", "Codeberg Explore", "code", "both",
                "https://codeberg.org/explore/repos",
                "بديل أوروبي — مشاريع خصوصية ومفتوحة تناسب مبدأ الخصوصية عندنا"),
    RadarSource("gitee", "Gitee Explore", "code", "evening",
                "https://gitee.com/explore",
                "المشاريع الصينية القوية التي لا تظهر في الترند الغربي"),
    RadarSource("sourceforge", "SourceForge", "code", "evening",
                "https://sourceforge.net/directory/",
                "برامج قديمة وجديدة — مناجم هندسة عكسية للأدوات الناضجة"),
    RadarSource("bitbucket", "Bitbucket Explore", "code", "evening",
                "https://bitbucket.org/repo/all",
                "مشاريع شركات وفرق — أنماط حوكمة الكود المؤسسي"),
    RadarSource("dockerhub", "Docker Hub", "packages", "evening",
                "https://hub.docker.com/search?q=&type=image",
                "صور جاهزة تُشغَّل بضغطة — مرشّحة لبيئات العزل والمحاكاة"),
    RadarSource("replicate", "Replicate Explore", "models", "evening",
                "https://replicate.com/explore",
                "نماذج تُجرَّب من المتصفح — تقييم سريع قبل التشغيل المحلي"),
)

_CATALOG_BY_NAME: dict[str, RadarSource] = {s.name: s for s in DEFAULT_CATALOG}


class Radar:
    """رادار التوليد — كتالوج ثابت وتقارير حتمية للفترتين."""

    def __init__(self, catalog: Iterable[RadarSource] | None = None) -> None:
        sources = tuple(catalog) if catalog is not None else DEFAULT_CATALOG
        seen: set[str] = set()
        for s in sources:
            if s.name in seen:
                raise ValueError(f"مصدر مكرر في الكتالوج: {s.name}")
            seen.add(s.name)
        self._sources: tuple[RadarSource, ...] = sources

    @property
    def sources(self) -> tuple[RadarSource, ...]:
        """الكتالوج كاملاً بترتيبه المعلن."""
        return self._sources

    def sources_for(self, cadence: str) -> tuple[RadarSource, ...]:
        """مصادر الفترة — «both» يظهر في الفترتين، والترتيب ثابت."""
        if cadence not in CADENCES:
            raise ValueError(f"فترة غير معروفة: {cadence} (المعروفة: {CADENCES})")
        return tuple(
            s for s in self._sources
            if s.cadence == cadence or s.cadence == "both"
        )

    def by_kind(self, cadence: str) -> dict[str, list[RadarSource]]:
        """مصادر الفترة مجموعة بنوعها — الأنواع الغائبة تُسقَط لا تُفرَّغ."""
        grouped: dict[str, list[RadarSource]] = {}
        for s in self.sources_for(cadence):
            grouped.setdefault(s.kind, []).append(s)
        return {k: grouped[k] for k in KINDS if k in grouped}

    def report(self, cadence: str, generated_at: str | None = None) -> str:
        """تقرير Markdown حتمي — بلا طابع زمني افتراضياً ليكون قابل المقارنة."""
        if cadence not in CADENCES:
            raise ValueError(f"فترة غير معروفة: {cadence} (المعروفة: {CADENCES})")
        when = generated_at or ""
        title = "تقرير الصباح" if cadence == "morning" else "تقرير المساء"
        lines: list[str] = [f"# {title} — رادار التوليد", ""]
        if when:
            lines.append(f"*أُنشئ: {when}*")
            lines.append("")
        grouped = self.by_kind(cadence)
        kind_label = {
            "code": "مستودعات ومشاريع",
            "models": "نماذج الذكاء",
            "packages": "مكتبات وصور تشغيل",
            "products": "منتجات وتطبيقات",
        }
        for kind in KINDS:
            if kind not in grouped:
                continue
            lines.append(f"## {kind_label[kind]}")
            lines.append("")
            lines.append("| المصدر | الرابط | المستفاد |")
            lines.append("|---|---|---|")
            for s in grouped[kind]:
                lines.append(f"| {s.label} | {s.url} | {s.benefit} |")
            lines.append("")
        total = len(self.sources_for(cadence))
        lines.append(f"**{total} مصدراً** في هذه الفترة من أصل {len(self._sources)} في الكتالوج.")
        lines.append("")
        lines.append("> الوضع الكتالوغي: بلا جلب شبكي — الجلب الحي عبر `live_digest` فقط.")
        lines.append("")
        return "\n".join(lines)

    def snapshot(self) -> str:
        """الكامل JSON حتمياً (sort_keys) — للفحص والدرّة."""
        return json.dumps(
            [asdict(s) for s in self._sources],
            ensure_ascii=False, sort_keys=True, indent=2,
        )


def live_digest(
    radar: Radar,
    fetcher: Callable[[RadarSource], str | None] | None,
    cadence: str,
) -> list[dict[str, str]]:
    """جلب حي معزول: دالة الجلب مُمرَّرة (عينها الاختبار يحقنها).

    كل مصدر ينتقل أو يعلن ``unavailable`` — لا استثناء يهدم القائمة،
    ولا شبكة إطلاقاً إن كان ``fetcher`` فارغاً.
    """
    if cadence not in CADENCES:
        raise ValueError(f"فترة غير معروفة: {cadence} (المعروفة: {CADENCES})")
    out: list[dict[str, str]] = []
    for s in radar.sources_for(cadence):
        if fetcher is None:
            out.append({"name": s.name, "status": "catalog", "digest": ""})
            continue
        try:
            text = fetcher(s)
        except Exception as exc:  # noqa: BLE001 — الجلب الحي لا يهدم أبداً
            out.append({"name": s.name, "status": "unavailable",
                        "digest": f"{type(exc).__name__}"})
            continue
        if text is None:
            out.append({"name": s.name, "status": "unavailable", "digest": ""})
        else:
            out.append({"name": s.name, "status": "ok",
                        "digest": str(text)[:400]})
    return out


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="radar", description="رادار التوليد — تقرير الصباح والمساء")
    parser.add_argument("--cadence", choices=CADENCES, default="morning")
    parser.add_argument("--out", default=None, help="مسار الملف (افتراضي: reports/radar-<فترة>.md)")
    parser.add_argument("--stamp", action="store_true", help="أضف طابع الإنشاء")
    parser.add_argument("--catalog", action="store_true", help="اطبع الكتالوج JSON ثم انتهِ")
    args = parser.parse_args(argv)

    radar = Radar()
    if args.catalog:
        print(radar.snapshot())
        return 0
    text = radar.report(args.cadence, generated_at=_now_stamp() if args.stamp else None)
    root = Path(__file__).resolve().parents[3]
    out_path = Path(args.out) if args.out else root / "reports" / f"radar-{args.cadence}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"radar: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
