"""القابلية للرصد — سجل أثر معياري + تتبّع عميق، بلا تبعيات خارجية.

طبقتان (docs/V2_ROADMAP.md م3):
    * ``trace``   — سطر JSON لكل تشغيل (Week-2): ts/agent/tool/duration_ms/outcome.
    * ``otrace``  — جلسات JSONL بشجرة spans بمعرّفات OTel-نمط،
      مُصدِّر OTLP اختياري (معطَّل افتراضيًا — الخوصصة افتراضية)،
      دوران + ضغط zlib، وخطوات replay جاهزة للـ PWA.
"""

from src.observability.otrace import (
    DeepTracer,
    OTLPExporter,
    list_sessions,
    replay_steps,
    sanitize_attributes,
)
from src.observability.trace import (
    trace_context,
    trace_event,
    trace_path,
    read_recent,
)

__all__ = [
    "DeepTracer",
    "OTLPExporter",
    "list_sessions",
    "replay_steps",
    "sanitize_attributes",
    "trace_context",
    "trace_event",
    "trace_path",
    "read_recent",
]
