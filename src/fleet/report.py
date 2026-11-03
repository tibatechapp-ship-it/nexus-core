"""CLI تقارير الأسطول — ``python3 -m src.fleet.report``.

يُشغّل الخط الكامل: جرد → مطابقة → فحص → قياس → ترتيب → كتابة التقارير
في ``reports/``. أوفلاين بالكامل وآمن على الهاتف/Cd الصغير.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.fleet.benchmark import benchmark, rank
from src.fleet.conformance import run_conformance
from src.fleet.inventory import build_inventory, reconcile, summary
from src.fleet.leaderboard import write_reports

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="تقارير أسطول الوكلاء")
    parser.add_argument(
        "--deep", action="store_true", help="نسخ فعلي للوكلاء الأساسيين وقياس زمن التشغيل"
    )
    parser.add_argument(
        "--out", default=str(ROOT / "reports"), help="مجلد الإخراج (افتراضه reports/)"
    )
    args = parser.parse_args(argv)

    records = build_inventory()
    recon = reconcile(records)
    conf = run_conformance(records, deep=args.deep)
    bench = benchmark(records, deep=args.deep)
    ranked = rank(records, conf, bench)
    out = write_reports(Path(args.out), summary(records), records, ranked, conf, recon)

    total = summary(records)["total"]
    counts = conf["counts"]
    print(
        f"الأسطول: {total} وكيلاً — سليم {counts['healthy']}، "
        f"منقوص {counts['degraded']}، مكسور {counts['broken']}"
    )
    tiers: dict[str, int] = {}
    for row in ranked:
        tiers[row["tier"]] = tiers.get(row["tier"], 0) + 1
    dist = " · ".join(f"{t}:{tiers.get(t, 0)}" for t in ("S", "A", "B", "C"))
    print(f"توزيع الطبقات: {dist}")
    top = ranked[0] if ranked else None
    bottom = ranked[-1] if ranked else None
    if top and bottom and top["score"] != bottom["score"]:
        print(f"مدى الدرجات: {top['score']} ({top['name']}) ← {bottom['score']} ({bottom['name']})")
    for name, value in recon.items():
        if not value:
            continue
        if name == "aliases":
            # ب2.1: توحيد معلن — معلومة لا إنذار
            shown = ", ".join(sorted(value))
            print(f"أسماء موحدة معلنة ({len(value)}): {shown}")
            continue
        print(f"تنبيه مطابقة {name}: {value}")
    for path in out:
        print(f"كُتب: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
