"""Fleet Leaderboard — التقارير المنشورة للأسطول.

يحوّل الجرد والمطابقة والترتيب إلى مخرجين منشورين: JSON آلي كامل،
ولوحة ترتيب Markdown للقراءة البشرية. الكتابة فقط داخل مجلد التقارير
الممرَّر — لا مسارات مطلقة ولا هروب منه.
"""

from __future__ import annotations

import json
from pathlib import Path

__all__ = ["render_markdown", "write_reports"]

_TIER_ICON = {"S": "🥇", "A": "🥈", "B": "🥉", "C": "⚠️"}

#: قاعدة بوابة الترقية المعلنة (ب3.2) — تظهر في التقرير كما هي
PROMOTION_RULE = "A→S requires eval_suite=passed via src.fleet.promotion (no manual overrides)"


def promotion_section() -> dict:
    """قسم سجل الترقية للتقرير — سجل حي من reports/promotion_log.json."""
    try:
        from src.fleet.promotion import read_log

        return {"rule": PROMOTION_RULE, "log": read_log()}
    except Exception:  # noqa: BLE001 — غياب السجل قائمة فارغة معلنة
        return {"rule": PROMOTION_RULE, "log": []}


#: الأهداف المعلنة لدين الإصدار (ب4.3 — v1.51.0)
DEBT_TARGETS = {
    "architectural_todos": 0,
    "known_broken": 0,
    "behavioral_categories_min": 8,
}


def debt_section() -> dict:
    """عدّادات الدين المقيس من مصادرها المعلنة (ب4.3).

    * ``architectural_todos`` — بنود وثيقة القيود المصنفة تأجيلاً معماريًا
      (الهدف: صفر — انظر ``docs/known-limitations.md``).
    * ``known_broken`` — مفاتيح عقد الصدق ``KNOWN_BROKEN`` في اختبارات
      المطابقة (الهدف: صفر منذ 1.48.1).
    * ``behavioral_categories_covered`` — عيّنات العقد السلوكي المعلنة
      في ``tests/test_fleet_behavioral_contract.py`` (الهدف: ≥8).
    """
    import re as _re

    root = Path(__file__).resolve().parents[2]
    try:
        doc = (root / "docs" / "known-limitations.md").read_text(encoding="utf-8")
        architectural = sum(
            1 for line in doc.splitlines() if "Architectural decision needed" in line
        )
    except OSError:
        architectural = -1  # وثيقة مفقودة = دين غير مقيس (يُعلن لا يُخفى)
    try:
        conftext = (root / "tests" / "test_fleet_conformance.py").read_text(encoding="utf-8")
        block = _re.search(r"KNOWN_BROKEN[^=]*=\s*\{([^}]*)\}", conftext, _re.DOTALL)
        known_broken = len(_re.findall(r'["\']([\w-]+)["\']\s*:', block.group(1))) if block else -1
    except OSError:
        known_broken = -1
    try:
        behavior = (root / "tests" / "test_fleet_behavioral_contract.py").read_text(
            encoding="utf-8"
        )
        samples = _re.search(r"CATEGORY_SAMPLES[^=]*=\s*\{(.*?)\n\}", behavior, _re.DOTALL)
        covered = len(_re.findall(r'"[\w-]+"\s*:', samples.group(1))) if samples else 0
    except OSError:
        covered = 0
    return {
        "targets": dict(DEBT_TARGETS),
        "architectural_todos": architectural,
        "known_broken": known_broken,
        "behavioral_categories_covered": covered,
        "at_target": (architectural == 0 and known_broken == 0 and covered >= 8),
    }


def render_markdown(inventory_summary: dict, ranked: list[dict], conformance: dict) -> str:
    """لوحة الترتيب النهائية — أعلى 25 صفًا + توزيع الطبقات + الصحة."""
    counts = conformance["counts"]
    total = inventory_summary["total"]
    lines: list[str] = [
        "# لوحة ترتيب أسطول الوكلاء",
        "",
        f"**الإصدار:** `{inventory_summary['version']}` — **إجمالي الوكلاء:** {total}",
        "",
        "## الصحة العامة",
        "",
        "| الحالة | العدد | النسبة |",
        "|---|---:|---:|",
    ]
    for status in ("healthy", "degraded", "broken"):
        n = counts[status]
        pct = round(100.0 * n / total, 1) if total else 0.0
        lines.append(f"| {status} | {n} | {pct}% |")

    lines += ["", "## التوزيع حسب الإطار", ""]
    for fw, n in inventory_summary["by_framework"].items():
        lines.append(f"- **{fw}**: {n}")

    tiers: dict[str, int] = {}
    for row in ranked:
        tiers[row["tier"]] = tiers.get(row["tier"], 0) + 1
    lines += ["", "## توزيع الطبقات", ""]
    for tier in ("S", "A", "B", "C"):
        n = tiers.get(tier, 0)
        lines.append(f"- **{tier}**: {n}")

    lines += [
        "",
        "## الترتيب (أعلى 25)",
        "",
        "# | الوكيل | الإطار | الدرجة | الطبقة | الحالة | استيراد ms | استدعاء ms",
        "---|---|---|---:|---|---|---:|---:",
    ]
    for row in ranked[:25]:
        icon = _TIER_ICON.get(row["tier"], "")
        run_ms = row.get("run_ms")
        run_txt = f"{run_ms}" if run_ms is not None else "—"
        lines.append(
            f"{row['rank']} | {row['name']} | {row['framework']} "
            f"| {row['score']:.2f} | {row['tier']} {icon} | {row['status']} "
            f"| {row['import_ms']} | {run_txt}"
        )
    lines += [
        "",
        "**قراءة الطبقات:** S ≥ 95، A ≥ 85، B ≥ 70، C ما دون.",
        "",
        "**الدرجة =** صحة 30٪ + سرعة استيراد 15٪ + اكتمال دخول 15٪ "
        "+ استدعاء 25٪ + SLO دور 15٪ (v1.49.0).",
        "",
        "**ميزان الاستدعاء:** 100 استدعاء ناجح، 40 بناء فقط بلا عقد "
        "استدعاء، 0 فشل أو غير مُقاس — ومن لا يُقاس لا يُمنح نقاط استدعاء.",
        "",
        "**القياس:** `mode: fake-clock` — بلا شبكة وبلا LLM حقيقي؛ "
        "ميزانيات SLO لكل دور في `src/fleet/benchmark.py` "
        "(`ROLE_SLO_BUDGETS`)، والتجاوز حتى 3× الميزانية يخفض المكوّن خطياً.",
        "",
        "التقرير الآلي الكامل: `reports/fleet_inventory.json`.",
        "",
    ]
    return "\n".join(lines)


def write_reports(
    outdir: Path,
    summary: dict,
    records: list,
    ranked: list[dict],
    conformance: dict,
    reconcile_report: dict,
) -> list[Path]:
    """كتابة JSON الكامل + لوحة Markdown داخل ``outdir`` (يُنشأ إن لزم)."""
    outdir.mkdir(parents=True, exist_ok=True)
    json_path = outdir / "fleet_inventory.json"
    md_path = outdir / "agent_leaderboard.md"
    payload = {
        "summary": summary,
        "reconcile": reconcile_report,
        "conformance_counts": conformance["counts"],
        "agents": [r.to_json() if hasattr(r, "to_json") else r for r in records],
        "ranking": ranked,
        # ب3.2 (v1.50.0): سجل الترقية في التقرير — كل بند يحمل eval_suite،
        # والقاعدة: لا ترقية إلى S بلا eval_suite=passed (بلا تخصيص يدوي)
        "promotion": promotion_section(),
        # ب4.3 (v1.51.0): عدّادات الدين المقيس مقابل أهدافها المعلنة
        "debt": debt_section(),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    md_path.write_text(render_markdown(summary, ranked, conformance), encoding="utf-8")
    return [json_path, md_path]
