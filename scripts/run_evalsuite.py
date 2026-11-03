#!/usr/bin/env python3
"""Run the eval suite with a REAL model provider (bridge outside src/).

جسر جناح التقييم إلى المزودين الحقيقيين. يعيش في ``scripts/`` عمداً: حارس
سلسلة التوريد (``tests/adversarial/test_security.py``) يمنع ``src/*`` من
استيراد ``connectors``، فهذا الملف — خارج ``src/`` — هو نقطة الدمج الوحيدة.

أمثلة:
  python scripts/run_evalsuite.py --connector glm --limit 8
  python scripts/run_evalsuite.py --connector glm-cloud --category fix
  python scripts/run_evalsuite.py --connector offline            # بلا شبكة

المتغيرات البيئية تُقرأ لحظة النداء (عقد BYOK): مفاتيح المزود في .env —
GLM السحابي يحتاج ZAI_TOKEN، والـglm المحلي يحتاج خادم vLLM على
GLM_LOCAL_URL (افتراضياً http://127.0.0.1:8000/v1).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from connectors.registry import get_connector_class, list_providers  # noqa: E402
from src.evalsuite import runner  # noqa: E402
from src.evalsuite.offline import offline_factory  # noqa: E402
from src.evalsuite.tasks import CATEGORIES  # noqa: E402


def main() -> int:
    """Parse args, build the shared connector, run, print, exit."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="scripts/run_evalsuite.py",
        description="جناح التقييم بموصل حقيقي — المفاتيح من البيئة لا من الأوامر",
    )
    parser.add_argument("--connector", default="glm",
                        help=f"offline أو واحد من: {', '.join(list_providers())}")
    parser.add_argument("--category", choices=CATEGORIES, default=None)
    parser.add_argument("--task", default=None,
                        help="مهمة واحدة بالمعرّف (مثال: fix-03)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", default="runs/evalsuite")
    parser.add_argument("--max-iterations", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    if args.connector == "offline":
        factory = offline_factory
    else:
        connector = get_connector_class(args.connector)()
        factory = lambda task: connector  # noqa: E731 — موصل واحد مشترك

    summary = asyncio.run(runner.run_suite(
        factory,
        category=args.category, task_id=args.task, limit=args.limit,
        out_dir=Path(args.out), max_iterations=args.max_iterations,
        test_timeout=args.timeout,
    ))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("ok_rate") == 1.0 and not summary.get("regressions") else 1


if __name__ == "__main__":
    raise SystemExit(main())
