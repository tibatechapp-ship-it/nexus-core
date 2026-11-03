"""CLI: ``python -m src.evalsuite`` — run the eval suite and print the report.

أمثلة:
  * العرض الكامل بلا شبكة (يثبت الخط أنبوبياً): ``python -m src.evalsuite``
  * عينة سريعة: ``python -m src.evalsuite --limit 8``
  * فئة واحدة: ``python -m src.evalsuite --category fix``
  * نموذج حقيقي: ``python scripts/run_evalsuite.py --connector glm``
    (الجسر خارج ``src/`` عمداً — حارس سلسلة التوريد يمنع ``src/*`` من
    استيراد ``connectors``، ولن نضعف الحارس لأجل راحة CLI).

يخرج ملخص JSON واحداً على stdout، ورمز الخروج 1 عند أي فشل أو انحدار.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from src.evalsuite import runner
from src.evalsuite.offline import offline_factory
from src.evalsuite.tasks import CATEGORIES


def build_parser() -> argparse.ArgumentParser:
    """CLI surface — stdlib only, offline by construction."""
    parser = argparse.ArgumentParser(
        prog="python -m src.evalsuite",
        description="جناح التقييم الداخلي — 50 مهمة فوق محرك المراحل الخمس (بلا شبكة)",
    )
    parser.add_argument("--category", choices=CATEGORIES, default=None,
                        help="حصر التشغيل على فئة واحدة")
    parser.add_argument("--task", default=None,
                        help="تشغيل مهمة واحدة بالمعرّف (مثال: fix-03)")
    parser.add_argument("--limit", type=int, default=None,
                        help="أقصى عدد مهام في هذا التشغيل")
    parser.add_argument("--out", default="runs/evalsuite",
                        help="مجلد التقرير (JSONL + ملخص)")
    parser.add_argument("--max-iterations", type=int, default=3,
                        help="أقصى تكرارات المحرك لكل مهمة")
    parser.add_argument("--timeout", type=int, default=90,
                        help="مهلة اختبارات كل مهمة بالثواني")
    return parser


async def _async_main(argv: list[str] | None) -> int:
    args = build_parser().parse_args(argv)
    out = Path(args.out)
    summary = await runner.run_suite(
        offline_factory,
        category=args.category, task_id=args.task, limit=args.limit,
        out_dir=out, max_iterations=args.max_iterations,
        test_timeout=args.timeout,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary.get("ok_rate") != 1.0 or summary.get("regressions"):
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point — never raises; failures surface as exit code 1."""
    try:
        return asyncio.run(_async_main(argv))
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        print("أُلغي التشغيل", file=sys.stderr)
        return 130
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
