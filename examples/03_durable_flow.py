#!/usr/bin/env python3
"""تنفيذ دوّم ببوابة بشرية — لقطات موقّعة + interrupt/resume (م2).

السير: checkpoint عند حدود المراحل → مقاطعة معلنة → محاولة تقدّم
تُرفض fail-closed → قرار بشري (approve) → استئناف — كل حلقة موقّعة
ومربوطة بسابقتها بسلسلة parent_sha.

    python3 examples/03_durable_flow.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    from src.durable import DurableFlow, InterruptPending

    with tempfile.TemporaryDirectory(prefix="nexus-ex03-") as tmp:
        flow = DurableFlow("demo-pipeline", store_dir=Path(tmp))

        # المرحلة 1: بناء (آمنة — تُحفظ موقّعة SHA-256/HMAC).
        state = {"artifact": "demo.zip", "checks": 3}
        flow.checkpoint("build", state)
        latest = flow.latest()
        print(f"checkpoint(build): seq={latest['seq']} موقّعة "
              "ومربوطة بسلسلة parent")

        state = flow.resume() or {}
        print("resume(): تحقّق من السلسلة كاملة ثم استأنف — صفر إعادة عمل")

        # المرحلة 2: نشر خطرة — مقاطعة معلنة، وأي تقدّم قبل القرار يُرفض.
        flow.interrupt("نشر يتطلب موافقة بشرية (HITL)")
        try:
            flow.checkpoint("publish", {"published": True})
        except InterruptPending:
            print("checkpoint قبل القرار: مرفوض fail-closed ✓")

        # القرار البشري: approve يطلق الاستئناف (reject كان يغلق نهائيًا).
        flow.resume_after_approval("approve", auditor="قائد-الإصدار")
        flow.checkpoint("publish", {**state, "published": True})
        final = flow.resume()
        print(f"resume_after_approval(approve) → publish ✓ "
              f"(seq={final['seq']}, stage={final['stage']})")
        print("الحالة النهائية:", final["payload"])
        print("كل انتقال مُدقَّق في سجل append-only غير قابل للتلاعب.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
