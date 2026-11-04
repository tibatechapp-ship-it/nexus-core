"""سير عمل دوّم: حفظ عند حدود المراحل، فشل يُستأنف لا يُعاد، وبوابة بشرية.

العقد (من docs/V2_ROADMAP.md م2):
* كل مرحلة تُحفظ كنقطة تفتيش موقّعة مرتبطة بسابقتها (سلسلة تكامل).
* الاستئناف يبدأ من آخر نقطة صحيحة — صفر إعادة عمل للمراحل المنجزة.
* ``interrupt()`` يجمّد السير حتى موافقة بشرية معلنة عبر
  ``resume_after_approval()``؛ الرفض يغلق السير نهائيًا (fail-closed).
* كل حدث إيقاف/موافقة/رفض يُسجَّل في سجل تدقيق غير قابل للتلاعب.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.durable.audit import AuditLog
from src.durable.snapshots import SnapshotError, load_snapshot, sign_snapshot

__all__ = [
    "DurableFlow",
    "FlowRejected",
    "InterruptPending",
]

_PAUSE_MARKER = "_paused.json"


class InterruptPending(Exception):
    """محاولة تقدّم والسير موقوف بانتظار قرار — ارفضه أو وافق صراحة."""


class FlowRejected(Exception):
    """رفض البشر السير — لا استئناف ممكن (fail-closed)."""


class DurableFlow:
    """سير مرحلي بحفظ موقّع وذاكرة استئناف وبوابة موافقة بشرية."""

    def __init__(
        self,
        flow_id: str,
        *,
        store_dir: Path,
        audit: AuditLog | None = None,
    ) -> None:
        if not flow_id or "/" in flow_id or flow_id.startswith("."):
            raise ValueError("flow_id غير صالح")
        self.flow_id = flow_id
        self.store = Path(store_dir) / flow_id
        self.store.mkdir(parents=True, exist_ok=True)
        # انتبه: `audit or ...` فخ كلاسيكي — AuditLog يعرّف __len__ فيصبح
        # السجل الفارغ falsy ويُستبدل بصمت. المقارنة الصريحة إلزامية.
        self.audit: AuditLog = audit if audit is not None else AuditLog(
            self.store / "audit.jsonl", actor=f"flow:{flow_id}"
        )
        if not (self.store / "audit.jsonl").exists():
            self.audit.append("flow_created", detail={"flow_id": flow_id})

    # -- checkpoints -----------------------------------------------------------
    def checkpoint(self, stage: str, state: dict[str, Any]) -> Path:
        """احفظ حالة مرحلة — يرفض التقدّم إن كان السير موقوفًا بانتظار قرار."""
        if self._paused_path().exists():
            raise InterruptPending(f"السير موقوف: اقرأ {self._paused_path().name} وقرر أولًا")
        seq = self._next_seq()
        parent = self._digest_of(seq - 1) if seq > 1 else None
        snap = sign_snapshot(state, stage=stage, parent_sha=parent)
        path = self.store / f"{seq:04d}-{stage}.json"
        path.write_text(json.dumps(snap, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        self.audit.append("checkpoint", detail={"stage": stage, "seq": seq, "file": path.name})
        return path

    def latest(self) -> dict[str, Any] | None:
        """آخر نقطة تفتيش {stage, seq, payload} أو None إن لم يوجد شيء."""
        seq = self._next_seq() - 1
        if seq < 1:
            return None
        path = self._path_of(seq)
        snap = load_snapshot(path)
        return {"stage": str(snap["snapshot"]["stage"]), "seq": seq, "payload": snap["snapshot"]["payload"]}

    def resume(self) -> dict[str, Any] | None:
        """استأنف من آخر نقطة: يتحقق من السلسلة كاملة أولًا.

        يعيد نفس شكل ``latest()``؛ سلسلة مكسورة ترفع SnapshotError قبل أي
        استخدام للحالة — الفساد يُكتشف لا يُورَّث.
        """
        seq = self._next_seq() - 1
        parent: str | None = None
        for i in range(1, seq + 1):
            snap = load_snapshot(self._path_of(i))
            body = snap["snapshot"]
            if body.get("parent_sha") != parent:
                raise SnapshotError(f"سلسلة مكسورة عند نقطة {i}: الربط لا يطابق")
            parent = str(snap["integrity"]["digest"])
        return self.latest()

    # -- human gate --------------------------------------------------------------
    def interrupt(self, reason: str) -> dict[str, Any]:
        """أوقف السير بانتظار قرار بشري — بلا سبب لا إيقاف.

        الإيقاف حالة معلنة (وسم ملف) لا استثناء خفي: بعده يرفض
        ``checkpoint()`` أي تقدّم بـ InterruptPending حتى يصدر قرار.
        """
        if not reason:
            raise ValueError("سبب الإيقاف مطلوب")
        marker = {"reason": reason, "decision": None}
        self._paused_path().write_text(json.dumps(marker, ensure_ascii=False), encoding="utf-8")
        record = self.audit.append("interrupt", detail={"reason": reason})
        return {"flow_id": self.flow_id, "reason": reason, "audit_seq": record["seq"]}

    def resume_after_approval(self, decision: str, auditor: str) -> None:
        """قرار بشري معلن: ``approve`` يطلق الاستئناف، ``reject`` يغلق السير."""
        if not auditor:
            raise ValueError("اسم المدقّق مطلوب")
        if decision not in ("approve", "reject"):
            raise ValueError("decision يجب أن تكون approve أو reject")
        marker = json.loads(self._paused_path().read_text(encoding="utf-8"))
        marker["decision"] = decision
        marker["auditor"] = auditor
        self._paused_path().write_text(json.dumps(marker, ensure_ascii=False), encoding="utf-8")
        self.audit.append(
            "human_decision",
            decision=decision,
            detail={"auditor": auditor, "reason": marker.get("reason", "")},
        )
        if decision == "reject":
            self.audit.append("flow_closed", decision="reject", detail={"auditor": auditor})
            raise FlowRejected(self.flow_id)
        self._paused_path().unlink()
        self.audit.append("resume", decision="approve", detail={"auditor": auditor})

    # -- internals ---------------------------------------------------------------
    def _paused_path(self) -> Path:
        return self.store / _PAUSE_MARKER

    def _path_of(self, seq: int) -> Path:
        matches = sorted(self.store.glob(f"{seq:04d}-*.json"))
        if not matches:
            raise SnapshotError(f"نقطة التفتيش {seq} مفقودة")
        return matches[0]

    def _next_seq(self) -> int:
        return len(list(self.store.glob("[0-9]" * 4 + "-*.json"))) + 1

    def _digest_of(self, seq: int) -> str | None:
        if seq < 1:
            return None
        return str(load_snapshot(self._path_of(seq))["integrity"]["digest"])
