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


def render_markdown(inventory_summary: dict, ranked: list[dict],
                    conformance: dict) -> str:
    """لوحة الترتيب النهائية — أعلى 25 صفًا + ملخص الصحة والإطارات."""
    counts = conformance["counts"]
    total = inventory_summary["total"]
    lines: list[str] = [
        "# لوحة ترتيب أسطول الوكلاء",
        "",
        f"**الإصدار:** `{inventory_summary['version']}` — "
        f"**إجمالي الوكلاء:** {total}",
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

    lines += [
        "",
        "## الترتيب (أعلى 25)",
        "",
        "# | الوكيل | الإطار | الدرجة | الطبقة | الحالة | استيراد ms",
        "---|---|---|---:|---|---|---:",
    ]
    for row in ranked[:25]:
        icon = _TIER_ICON.get(row["tier"], "")
        lines.append(
            f"{row['rank']} | {row['name']} | {row['framework']} "
            f"| {row['score']:.2f} | {row['tier']} {icon} | {row['status']} "
            f"| {row['import_ms']}"
        )
    lines += [
        "",
        "**قراءة الطبقات:** S ≥ 95، A ≥ 85، B ≥ 70، C ما دون — "
        "الدرجة = صحة 50٪ + سرعة استيراد 25٪ + اكتمال دخول 25٪.",
        "",
        "التقرير الآلي الكامل: `reports/fleet_inventory.json`.",
        "",
    ]
    return "\n".join(lines)


def write_reports(outdir: Path, summary: dict, records: list, ranked: list[dict],
                  conformance: dict, reconcile_report: dict) -> list[Path]:
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
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    md_path.write_text(
        render_markdown(summary, ranked, conformance), encoding="utf-8"
    )
    return [json_path, md_path]
