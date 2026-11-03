"""Automated report for the eval suite — rates, timings, regressions.

التقرير الآلي (بند قبول M3.2): معدلات النجاح كلياً ولكل فئة، وأزمنة p50/p95،
وانحدارات مقارنة بالتشغيل السابق (مهمة نجحت ثم فشلت). كل الأرقام مشتقة من
سجلات المهام فقط — لا تقدير ولا تخمين.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

RECORDS_NAME = "evalsuite.jsonl"
SUMMARY_NAME = "evalsuite_summary.json"


def _percentile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank percentile on a pre-sorted list (deterministic)."""
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, max(0, round(q * (len(sorted_values) - 1))))
    return sorted_values[idx]


def _durations(records: list) -> dict:
    values = sorted(float(r["duration_ms"]) for r in records
                    if isinstance(r.get("duration_ms"), (int, float))
                    and r["duration_ms"] >= 0)
    if not values:
        return {"p50_ms": None, "p95_ms": None}
    return {"p50_ms": _percentile(values, 0.50), "p95_ms": _percentile(values, 0.95)}


def summarize(records: list) -> dict:
    """Success rates overall and per category, plus timing percentiles."""
    total = len(records)
    ok = sum(1 for r in records if r.get("ok") is True)
    by_category: dict[str, dict] = {}
    for cat in ("create", "fix", "test", "docs"):
        sub = [r for r in records if r.get("category") == cat]
        ok_sub = sum(1 for r in sub if r.get("ok") is True)
        by_category[cat] = {
            "total": len(sub), "ok": ok_sub,
            "rate": round(ok_sub / len(sub), 4) if sub else None,
        }
    return {
        "total": total,
        "ok": ok,
        "failed": total - ok,
        "ok_rate": round(ok / total, 4) if total else None,
        "by_category": by_category,
        "durations_ms": _durations(records),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def find_regressions(records: list, previous_records: list) -> list[str]:
    """Task ids that passed before and fail now — the suite's red line."""
    prev_ok = {r.get("id") for r in previous_records if r.get("ok") is True}
    now_failed = {r.get("id") for r in records if r.get("ok") is not True}
    return sorted(prev_ok & now_failed)


def read_previous_records(out_dir: Path) -> list:
    """Load the last run's records; empty list when absent or unreadable."""
    path = Path(out_dir) / RECORDS_NAME
    if not path.exists():
        return []
    records: list = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                records.append(rec)
    except OSError:
        return []
    return records


def write_report(out_dir: Path, records: list, summary: dict) -> tuple:
    """Persist JSONL records + summary JSON; returns both paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    records_path = out / RECORDS_NAME
    with open(records_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    summary_path = out / SUMMARY_NAME
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return records_path, summary_path
