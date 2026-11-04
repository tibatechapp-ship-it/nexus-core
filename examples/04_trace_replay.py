#!/usr/bin/env python3
"""تتبّع عميق + استرجاع بصري — شجرة spans بمعرّفات OTel (م3).

    python3 examples/04_trace_replay.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("NEXUS_OTLP_ENDPOINT", "")  # الخصوصية افتراضية


def main() -> int:
    from src.observability.otrace import DeepTracer, replay_steps

    with tempfile.TemporaryDirectory(prefix="nexus-ex04-") as tmp:
        tracer = DeepTracer(session_dir=Path(tmp))
        with tracer.session():
            with tracer.span("council.deliberate", agent="council",
                             attributes={"rounds": 2}) as root:
                with tracer.span("council.round", agent="analyst",
                                 attributes={"round": 1}):
                    pass
                with tracer.span("council.round", agent="critic",
                                 attributes={"round": 2}):
                    pass
        print("معرّف الجلسة:", tracer.trace_id)
        print("الملف:", tracer.path.name)

        steps = replay_steps(tracer.path)
        print(f"خطوات مسجّلة: {len(steps)} — بترتيب البدء:")
        for s in steps:
            depth = "  " if s["parent_span_id"] else ""
            print(f"  {depth}· {s['name']} "
                  f"({s['agent']}, {s['duration_ms']}ms, {s['outcome']})")
        assert steps[0]["parent_span_id"] == ""          # الجذر أولًا
        assert steps[1]["parent_span_id"] == root.span_id  # الأبناء معلّقون
        print("الخصوصية: بلا OTLP (NEXUS_OTLP_ENDPOINT فارغ) — "
              "لا شيء غادر الجهاز.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
