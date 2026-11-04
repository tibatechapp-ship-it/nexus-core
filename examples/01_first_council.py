#!/usr/bin/env python3
"""أول مجلس في 5 دقائق — مداولة تحليلية عبر CouncilEngine.

يعمل بلا مفاتيح وبلا إنترنت: نُبطّن المزوّد بمولّد mock حتمي
(نفس تقنية لوحة التحكم) — انظر الملاحظة في نهاية الملف.

    python3 examples/01_first_council.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("NEXUS_ALLOW_OPEN", "1")
os.environ.setdefault("NOVAMIND_HOME", str(
    Path(__file__).resolve().parents[1]))

# بيئة مغلقة: مولّد mock حتمي (نفس دالة لوحة التحكم src/web/app.py).
from src.web.app import _setup_mock  # noqa: E402

_setup_mock()


def main() -> int:
    from src.council.engine import CouncilEngine

    engine = CouncilEngine()
    engine.MAX_ROUNDS = 1
    result = engine.deliberate(
        "هل نعتمد SQLite أم PostgreSQL لنظام يعمل على الهاتف؟")
    print("الحكم:", result.verdict)
    print("الدرجة:", round(result.score, 3))
    print("الأعضاء:", [m["member"] for m in result.transcript
                       if isinstance(m, dict)])
    print("أحداث أمنية:", len(result.security_events))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
