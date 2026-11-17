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
import re
import uuid
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
        self._recover_pending_interrupt()

    def _recover_pending_interrupt(self) -> None:
        """Rebuild a pause marker if a crash followed the durable interrupt audit."""
        events = self.audit.read()
        pending: dict[str, Any] | None = None
        resolved: set[str] = set()
        for event in events:
            detail = event.get("detail", {})
            interruption_id = detail.get("interruption_id")
            if event.get("event") == "interrupt" and interruption_id:
                pending = event
            elif event.get("event") in {"human_decision", "resume", "flow_closed"} and interruption_id:
                resolved.add(str(interruption_id))
        if pending is None:
            return
        detail = pending.get("detail", {})
        interruption_id = str(detail.get("interruption_id", ""))
        if interruption_id in resolved or self._paused_path().exists():
            return
        marker = {
            "reason": str(detail.get("reason", "")),
            "decision": None,
            "interruption_id": interruption_id,
        }
        marker_path = self._paused_path()
        temporary = marker_path.with_suffix(marker_path.suffix + ".tmp")
        temporary.write_text(json.dumps(marker, ensure_ascii=False), encoding="utf-8")
        temporary.replace(marker_path)

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
        inventory = self._checkpoint_inventory()
        if not inventory:
            return None
        seq = max(inventory)
        snap = load_snapshot(inventory[seq])
        return {"stage": str(snap["snapshot"]["stage"]), "seq": seq, "payload": snap["snapshot"]["payload"]}

    def resume(self) -> dict[str, Any] | None:
        """استأنف من آخر نقطة بعد التحقق من المخزون والسلسلة كاملة."""
        inventory = self._checkpoint_inventory()
        parent: str | None = None
        for i in sorted(inventory):
            snap = load_snapshot(inventory[i])
            body = snap["snapshot"]
            if body.get("parent_sha") != parent:
                raise SnapshotError(f"سلسلة مكسورة عند نقطة {i}: الربط لا يطابق")
            parent = str(snap["integrity"]["digest"])
        return self.latest()

    # -- human gate --------------------------------------------------------------
    @property
    def is_interrupted(self) -> bool:
        """Whether this flow is paused for an explicit human decision."""
        return self._paused_path().exists()

    @property
    def is_rejected(self) -> bool:
        """Whether a terminal human rejection has been durably recorded."""
        marker_path = self._paused_path()
        if not marker_path.exists():
            return False
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return marker.get("decision") == "reject"

    def interrupt(self, reason: str) -> dict[str, Any]:
        """أوقف السير بانتظار قرار بشري — بلا سبب لا إيقاف.

        الإيقاف حالة معلنة (وسم ملف) لا استثناء خفي: بعده يرفض
        ``checkpoint()`` أي تقدّم بـ InterruptPending حتى يصدر قرار.
        """
        if not reason:
            raise ValueError("سبب الإيقاف مطلوب")
        if self.is_interrupted:
            raise InterruptPending("السير متوقف بالفعل بانتظار قرار بشري")
        interruption_id = uuid.uuid4().hex
        # Write-ahead audit: if marker creation crashes, __init__ reconstructs it.
        record = self.audit.append(
            "interrupt",
            detail={"reason": reason, "interruption_id": interruption_id},
        )
        marker = {
            "reason": reason,
            "decision": None,
            "interruption_id": interruption_id,
        }
        marker_path = self._paused_path()
        temporary = marker_path.with_suffix(marker_path.suffix + ".tmp")
        temporary.write_text(json.dumps(marker, ensure_ascii=False), encoding="utf-8")
        temporary.replace(marker_path)
        return {
            "flow_id": self.flow_id,
            "reason": reason,
            "audit_seq": record["seq"],
            "interruption_id": interruption_id,
        }

    def resume_after_approval(self, decision: str, auditor: str) -> None:
        """Apply an idempotent human decision, recovering interrupted writes."""
        if not auditor:
            raise ValueError("اسم المدقّق مطلوب")
        if decision not in ("approve", "reject"):
            raise ValueError("decision يجب أن تكون approve أو reject")
        if not self.is_interrupted:
            raise ValueError("لا يوجد قرار بشري معلّق")

        marker_path = self._paused_path()
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        recorded = marker.get("decision")
        recorded_auditor = marker.get("auditor")
        if recorded is not None and (recorded != decision or recorded_auditor != auditor):
            raise ValueError("تم تسجيل قرار مختلف لهذا الإيقاف مسبقًا")

        # Persist the decision atomically before any state transition. A retry
        # with the same actor/decision completes the transition after a crash.
        if recorded is None:
            marker["decision"] = decision
            marker["auditor"] = auditor
            temporary = marker_path.with_suffix(marker_path.suffix + ".tmp")
            temporary.write_text(json.dumps(marker, ensure_ascii=False), encoding="utf-8")
            temporary.replace(marker_path)

        events = self.audit.read()
        matching = [
            event for event in events
            if event.get("event") == "human_decision"
            and event.get("decision") == decision
            and event.get("detail", {}).get("auditor") == auditor
            and event.get("detail", {}).get("reason") == marker.get("reason", "")
            and event.get("detail", {}).get("interruption_id") == marker.get("interruption_id")
        ]
        if not matching:
            self.audit.append(
                "human_decision",
                decision=decision,
                detail={
                    "auditor": auditor,
                    "reason": marker.get("reason", ""),
                    "interruption_id": marker.get("interruption_id"),
                },
            )

        if decision == "reject":
            closed = [
                event for event in self.audit.read()
                if event.get("event") == "flow_closed"
                and event.get("decision") == "reject"
                and event.get("detail", {}).get("auditor") == auditor
                and event.get("detail", {}).get("interruption_id") == marker.get("interruption_id")
            ]
            if not closed:
                self.audit.append(
                    "flow_closed",
                    decision="reject",
                    detail={"auditor": auditor, "interruption_id": marker.get("interruption_id")},
                )
            raise FlowRejected(self.flow_id)

        marker_path.unlink()
        resumed = [
            event for event in self.audit.read()
            if event.get("event") == "resume"
            and event.get("decision") == "approve"
            and event.get("detail", {}).get("auditor") == auditor
            and event.get("detail", {}).get("interruption_id") == marker.get("interruption_id")
        ]
        if not resumed:
            self.audit.append(
                "resume",
                decision="approve",
                detail={"auditor": auditor, "interruption_id": marker.get("interruption_id")},
            )

    # -- internals ---------------------------------------------------------------
    def _paused_path(self) -> Path:
        return self.store / _PAUSE_MARKER

    def _checkpoint_inventory(self) -> dict[int, Path]:
        """Return a strict, contiguous checkpoint inventory or fail closed.

        Duplicate sequence numbers, gaps, malformed numbered JSON files, and
        symlinked checkpoint files are ambiguous history and must never be
        silently ignored or selected by filename sort order.
        """
        inventory: dict[int, Path] = {}
        for path in self.store.iterdir():
            if path.suffix != ".json" or not path.name[:1].isdigit():
                continue
            match = re.fullmatch(r"(\\d+)-(.+)\\.json", path.name)
            if match is None:
                raise SnapshotError(f"اسم نقطة تفتيش غير صالح: {path.name}")
            if path.is_symlink() or not path.is_file():
                raise SnapshotError(f"ملف نقطة التفتيش ليس ملفًا عاديًا: {path.name}")
            seq = int(match.group(1))
            if seq < 1:
                raise SnapshotError(f"رقم نقطة تفتيش غير صالح: {path.name}")
            if seq in inventory:
                raise SnapshotError(f"رقم نقطة تفتيش مكرر: {seq}")
            inventory[seq] = path

        if inventory:
            expected = set(range(1, max(inventory) + 1))
            actual = set(inventory)
            if actual != expected:
                missing = min(expected - actual)
                raise SnapshotError(f"نقطة التفتيش {missing} مفقودة من السلسلة")
        return inventory

    def _path_of(self, seq: int) -> Path:
        inventory = self._checkpoint_inventory()
        try:
            return inventory[seq]
        except KeyError as exc:
            raise SnapshotError(f"نقطة التفتيش {seq} مفقودة") from exc

    def _next_seq(self) -> int:
        inventory = self._checkpoint_inventory()
        return max(inventory, default=0) + 1

    def _digest_of(self, seq: int) -> str | None:
        if seq < 1:
            return None
        return str(load_snapshot(self._path_of(seq))["integrity"]["digest"])
