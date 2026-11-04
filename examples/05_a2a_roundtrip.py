#!/usr/bin/env python3
"""دورة A2A كاملة — اكتشاف → رسالة → رد بلا شبكة (م4).

يستخدم عميل A2A حقيقيًا نحو نقطتنا عبر نقل مُحقن (حتى يعمل المثال
في أي بيئة بلا خادم قائم) — القاعدة نفسها: الصادر بقائمة سماح.

    python3 examples/05_a2a_roundtrip.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    from src.a2a import A2AClient, handle_jsonrpc, validate_card

    # (1) الاكتشاف: بطاقة المنصة من المسار الشهير.
    card = handle_jsonrpc.__globals__  # noqa: F841 — مجرد إشارة للوحدة
    from src.a2a import build_hub_card
    hub = build_hub_card("http://localhost:8000").to_dict()
    problems = validate_card(hub)
    print("بطاقة المركز:", hub["name"], "| صالحة:",
          problems == [], "| skills:", [s["id"] for s in hub["skills"]])

    # (2) رسالة → (3) رد: JSON-RPC 2.0 عبر المُرسِل مباشرةً
    # (في النشر الحقيقي: POST /api/a2a/message).
    reply = handle_jsonrpc({
        "jsonrpc": "2.0", "id": 1, "method": "message/send",
        "params": {"message": {
            "role": "user", "kind": "message", "messageId": "demo-1",
            "parts": [{"type": "text", "text": "سلام من وكيل خارجي"}],
        }},
    })
    assert "result" in reply
    text = reply["result"]["parts"][0]["text"]
    print("رد الوكيل:", text[:80], "…")

    # (4) العميل الصادر: القاعدة — لا اتصال إلا بسماح صريحة.
    client = A2AClient("http://localhost:8000", allowlist=[])
    try:
        client.fetch_card()
    except PermissionError:
        print("الصادر بلا سماح: مرفوض (PrivacyError) — الخصوصية افتراضية.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
