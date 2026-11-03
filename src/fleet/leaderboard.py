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
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    md_path.write_text(render_markdown(summary, ranked, conformance), encoding="utf-8")
    return [json_path, md_path]
