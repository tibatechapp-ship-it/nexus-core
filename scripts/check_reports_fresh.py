#!/usr/bin/env python3
"""بوابة نضارة التقارير في CI (ب4.1 — v1.51.0).

تعيد توليد تقرير الأسطول في مجلد مؤقت وتقارن **الجوهر الدلالي المستقر**
بالمعتمد في ``reports/`` — ما يجب ألا يتقادم أبداً:

* الهوية: (framework, name, role, category, canonical) لكل وكيل.
* المطابقة: reconcile (aliases + التعارضات + الملفات المفقودة).
* القياس الصادق: كل وكيل novamind له ``run_ms`` غير-null.
* سجل الترقية: قاعدة البوابة المعلنة.
* الإصدار: ``summary.version == pyproject`` (تقارير إصدار لا قديمة).

الحقول المتقلبة بالبيئة (``import_ms``/``run_ms``/``score``/``tier``/
``status`` الحساسة للاختيارات) تُستبعد من المقارنة عمداً — بوابة النضارة
هنا تمنع «التقارير القديمة» (ف5) لا «الأرقام غير المتطابقة عبر الأجهزة».

الخروج: 0 = معتمد ونظيف، 1 = تقارير قديمة/منحرفة (يُفشل CI).
"""

from __future__ import annotations

import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.fleet.report import main as report_main  # noqa: E402

REPORT = ROOT / "reports" / "fleet_inventory.json"


def _repo_version() -> str:
    with open(ROOT / "pyproject.toml", "rb") as f:
        return str(tomllib.load(f)["project"]["version"])


def _identities(payload: dict) -> set[tuple]:
    return {
        (a["framework"], a["name"], a["role"], a["category"], bool(a.get("canonical", True)))
        for a in payload.get("agents", [])
    }


def _novamind_measured(payload: dict) -> set[str]:
    return {
        r["name"]
        for r in payload.get("ranking", [])
        if r.get("framework") == "novamind" and r.get("run_ms") is not None
    }


def main() -> int:
    if not REPORT.is_file():
        print("FAIL: reports/fleet_inventory.json مفقود")
        return 1
    committed = __import__("json").loads(REPORT.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="reports-fresh-") as tmp:
        code = report_main(["--deep", "--out", tmp])
        if code != 0:
            print("FAIL: توليد التقرير الحي فشل")
            return 1
        fresh = __import__("json").loads(
            (Path(tmp) / "fleet_inventory.json").read_text(encoding="utf-8")
        )

    problems: list[str] = []

    if committed.get("summary", {}).get("version") != _repo_version():
        problems.append(
            f"summary.version ({committed.get('summary', {}).get('version')}) "
            f"!= pyproject ({_repo_version()}) — تقارير قديمة"
        )

    committed_ids = _identities(committed)
    fresh_ids = _identities(fresh)
    if committed_ids != fresh_ids:
        missing = fresh_ids - committed_ids
        extra = committed_ids - fresh_ids
        problems.append(
            f"هوية الوكلاء انحرفت عن الجيل الحالي — ناقص: {sorted(missing)[:4]} "
            f"زائد: {sorted(extra)[:4]} — جدّد التقارير"
        )

    for key in (
        "duplicates",
        "cross_framework_overlap",
        "bad_category",
        "bad_criticality",
        "missing_module_file",
    ):
        if committed.get("reconcile", {}).get(key) != fresh.get("reconcile", {}).get(key):
            problems.append(f"reconcile.{key} انحرف — جدّد التقارير")
    if set(committed.get("reconcile", {}).get("aliases", {})) != set(
        fresh.get("reconcile", {}).get("aliases", {})
    ):
        problems.append("reconcile.aliases انحرفت — جدّد التقارير")

    committed_measured = _novamind_measured(committed)
    fresh_measured = _novamind_measured(fresh)
    unmeasured = fresh_measured == set() and committed_measured == set()
    if not unmeasured and committed_measured != fresh_measured:
        problems.append("تغطية قياس novamind (run_ms) انحرفت عن الجيل الحالي — جدّد")
    if len(fresh_measured) != len(fresh.get("ranking", [])) - (
        len([r for r in fresh.get("ranking", []) if r["framework"] != "novamind"])
    ):
        problems.append("وكلاء novamind بلا run_ms في الجيل الحالي")

    committed_rule = (committed.get("promotion") or {}).get("rule")
    fresh_rule = (fresh.get("promotion") or {}).get("rule")
    if committed_rule != fresh_rule:
        problems.append("قاعدة بوابة الترقية انحرفت — جدّد التقارير")

    if problems:
        print("FAIL: التقارير المعتمدة ليست نضرة:")
        for p in problems:
            print(f"  - {p}")
        print("شغّل: python3 -m src.fleet.report --deep وأدرج التجديد")
        return 1
    print(
        f"OK: التقارير نضرة عند إصدار {_repo_version()} "
        f"({len(committed_ids)} وكيلاً، {len(_novamind_measured(committed))} مقيساً)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
