"""الحزمة الدوّمة — لقطات موقّعة، سجل تدقيق، وسير مرحلي ببوابة بشرية.

المدخل العام لـ ``src/durable`` (docs/V2_ROADMAP.md م2)::

    from src.durable import AuditLog, DurableFlow

    flow = DurableFlow("demo", store_dir=Path("runs/durable"))
    flow.checkpoint("risk", {"level": "low"})
    last = flow.resume()   # (مرحلة, حالة) بعد أي انقطاع — بلا إعادة عمل
"""

from __future__ import annotations

from src.durable.audit import AuditIntegrityError, AuditLog
from src.durable.flow import DurableFlow, FlowRejected, InterruptPending
from src.durable.snapshots import SnapshotError, canonical_json, sign_snapshot, verify_snapshot

__all__ = [
    "AuditIntegrityError",
    "AuditLog",
    "DurableFlow",
    "FlowRejected",
    "InterruptPending",
    "SnapshotError",
    "canonical_json",
    "sign_snapshot",
    "verify_snapshot",
]
