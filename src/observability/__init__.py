"""القابلية للرصد — سجل أثر معياري (trace logs) بلا تبعيات خارجية.

Week-2 معلم خارطة المنتَجة: كل تشغيل وكيل/مجلس يكتب سطر JSON واحداً في
``runs/trace.jsonl`` بالحقول الإلزامية ts/agent/tool/duration_ms/outcome.
"""

from src.observability.trace import (
    trace_context,
    trace_event,
    trace_path,
    read_recent,
)

__all__ = ["trace_context", "trace_event", "trace_path", "read_recent"]
