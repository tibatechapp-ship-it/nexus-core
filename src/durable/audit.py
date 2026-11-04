"""سجل تدقيق ملحق-فقط (append-only) ببصمات متسلسلة.

كل حدث يُلحق كسطر JSONL في ملف واحد؛ كل سطر يحمل بصمة HMAC/SHA-256 لمحتواه
وبصمة السطر السابق — أي حذف أو تعديل أو إعادة ترتيب تكسر السلسلة ويكشفها
``read()``. هذا هو العقد: كل موافقة بشرية (HITL) تُنتج سجلًا يقرؤه اختبار.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any

__all__ = ["AuditIntegrityError", "AuditLog"]

_KEY_ENV = "NEXUS_DURABLE_KEY"


class AuditIntegrityError(Exception):
    """سجل التدقيق تلاعب به: سطر محذوف/معدّل/مرتَّب من جديد."""


def _key() -> bytes:
    raw = os.environ.get(_KEY_ENV, "").strip()
    return raw.encode("utf-8") if raw else b""


def _digest(body: bytes, key: bytes, prev: str) -> str:
    chain = body + b"|" + prev.encode("utf-8")
    if key:
        return hmac.new(key, chain, hashlib.sha256).hexdigest()
    return hashlib.sha256(chain).hexdigest()


class AuditLog:
    """ملف JSONL واحد: أسطر ملحقة فقط، سلسلة بصمات تكشف أي تلاعب."""

    def __init__(self, path: Path, *, actor: str = "system") -> None:
        self.path = Path(path)
        self.actor = actor
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: str, *, decision: str | None = None, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        """ألحق حدثًا؛ يُعاد السجل الكامل للحدث (مع بصرته وموضعه في السلسلة)."""
        if not event:
            raise ValueError("event مطلوب")
        prev = self._last_digest()
        record = {
            "seq": self._count_lines(),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "actor": self.actor,
            "event": event,
            "decision": decision,
            "detail": detail or {},
            "prev": prev,
        }
        blob = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        record["digest"] = _digest(blob, _key(), prev)
        line = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        return record

    def read(self) -> list[dict[str, Any]]:
        """اقرأ السلسلة كاملة وتحقق منها — أي تلاعب يرفع AuditIntegrityError."""
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        prev = ""
        with self.path.open("r", encoding="utf-8") as fh:
            for lineno, raw in enumerate(fh, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError as exc:
                    raise AuditIntegrityError(f"سطر {lineno} ليس JSON صالحًا") from exc
                declared = rec.pop("digest", None)
                blob = json.dumps(rec, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                if rec.get("prev", "") != prev:
                    raise AuditIntegrityError(f"سطر {lineno}: سلسلة الربط مكسورة")
                expected = _digest(blob, _key(), prev)
                if not hmac.compare_digest(str(declared), expected):
                    raise AuditIntegrityError(f"سطر {lineno}: البصمة لا تطابق (تلاعب أو فساد)")
                rec["digest"] = declared
                prev = str(declared)
                records.append(rec)
        return records

    def events(self, event: str) -> list[dict[str, Any]]:
        """جميع سجلات نوع حدث معيّن (بعد التحقق الكامل للسلسلة)."""
        return [r for r in self.read() if r.get("event") == event]

    def __len__(self) -> int:
        return len(self.read())

    # -- internals ------------------------------------------------------------
    def _count_lines(self) -> int:
        if not self.path.exists():
            return 0
        with self.path.open("r", encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip())

    def _last_digest(self) -> str:
        if not self.path.exists():
            return ""
        last = ""
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = line
        if not last:
            return ""
        try:
            return str(json.loads(last).get("digest", ""))
        except ValueError:
            return ""
