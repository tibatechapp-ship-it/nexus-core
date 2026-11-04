"""لقطات دوّمة موقّعة — سلامة البيانات لا الخفاء.

كل لقطة JSON مُعيَّرة (sorted keys) وتحمل بصمة SHA-256 لمحتواها؛ وعند توفر
مفتاح (متغير البيئة ``NEXUS_DURABLE_KEY``) تُحسب بصمة HMAC-SHA256 بدلها
فتصبح الشهادة صادقة لا مكشوفة التعديل فقط. السلسلة تُبنى بربط كل لقطة
ببصمة سابقتها (``parent_sha``) — أي تلاعب بأي حلقة يكسر كل الحلقات اللاحقة.

stdlib خالص: hashlib + hmac + json + time.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any

__all__ = ["SnapshotError", "canonical_json", "sign_snapshot", "verify_snapshot"]

_KEY_ENV = "NEXUS_DURABLE_KEY"


class SnapshotError(Exception):
    """لقطة غير صالحة: بصمة لا تطابق أو بنية مكسورة."""


def _integrity_key() -> bytes | None:
    """مفتاح HMAC من البيئة — بلا مفتاح تكون الحماية تكاملًا لا صدقًا."""
    raw = os.environ.get(_KEY_ENV, "").strip()
    return raw.encode("utf-8") if raw else None


def canonical_json(payload: Any) -> bytes:
    """تمثيل JSON المعياري: مفاتيح مرتبة، UTF-8 صريح، بلا مسافات زائدة."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _digest(body: bytes, key: bytes | None) -> str:
    if key is None:
        return hashlib.sha256(body).hexdigest()
    return hmac.new(key, body, hashlib.sha256).hexdigest()


def sign_snapshot(payload: Any, *, stage: str, parent_sha: str | None = None, key: bytes | None = None) -> dict[str, Any]:
    """غلّف الحالة في لقطة موقّعة قابلة للتدقيق.

    ``key=None`` يقرأ المفتاح من ``NEXUS_DURABLE_KEY`` تلقائيًا؛ تمرير
    ``key=b""`` يفرض وضع SHA-256 الصريح (تكامل بلا صدق — مفيد للاختبارات).
    """
    if key is None:
        key = _integrity_key() or b""
    if not stage:
        raise SnapshotError("stage مطلوب للقطة")
    body = {
        "stage": stage,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "parent_sha": parent_sha,
        "payload": payload,
    }
    blob = canonical_json(body)
    return {
        "integrity": {
            "algorithm": "hmac-sha256" if key else "sha256",
            "digest": _digest(blob, key or None),
        },
        "snapshot": body,
    }


def verify_snapshot(snap: dict[str, Any], *, key: bytes | None = None) -> bool:
    """تحقق زمن-ثابت من البصمة؛ يرفع SnapshotError عند بنية مكسورة."""
    try:
        integ = snap["integrity"]
        body = snap["snapshot"]
        declared = integ["digest"]
        algo = integ["algorithm"]
    except (KeyError, TypeError) as exc:
        raise SnapshotError(f"بنية لقطة مكسورة: {exc}") from exc
    if algo not in ("sha256", "hmac-sha256"):
        raise SnapshotError(f"خوارزمية غير معلومة: {algo!r}")
    if key is None:
        key = _integrity_key() or b""
    expected_algo = "hmac-sha256" if key else "sha256"
    if algo != expected_algo:
        return False  # مفتاح الحاضر لا يطابق وضع اللقطة — لا تصدّقها
    recomputed = _digest(canonical_json(body), key or None)
    return hmac.compare_digest(str(declared), recomputed)


def load_snapshot(path: Path, *, key: bytes | None = None) -> dict[str, Any]:
    """اقرأ لقطة من ملف وتحقق منها — التلاعب يرفع SnapshotError."""
    import json as _json

    try:
        snap = _json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SnapshotError(f"لا يمكن قراءة اللقطة {path.name}: {exc}") from exc
    if not verify_snapshot(snap, key=key):
        raise SnapshotError(f"بصمة اللقطة لا تطابق: {path.name}")
    return snap
