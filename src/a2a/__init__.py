"""A2A — التشغيل البيني بين الوكلاء (Agent-to-Agent) — stdlib فقط.

نسخة المواصفة المثبَّطة: **A2A 0.3.0 (لقطة 2025-11، نقل JSONRPC فقط)** —
موثّقة في ``docs/A2A.md`` وتُرفع بمراجعة معلنة (نفس منهجية MCP مع
2026-07-28). الجزئية المنفذة: بطاقة الوكيل (Agent Card) + دورة
اكتشاف/رسالة/رد عبر JSON-RPC 2.0 غير المتدفق. البثّ وpushNotifications
غير منفذان (``capabilities`` تعلن ذلك بصدق).

المعلم (docs/V2_ROADMAP.md م4 — ض3):
    * **بطاقة من مصدر واحد للحقيقة**: 106 بطاقة تُولَّد تلقائيًا من جرد
      الأسطول الحي (``src.fleet.build_inventory``) — لا قوائم مكررة.
    * **ثنائية الاتجاه**: نحن نعرض بطاقات ونستقبل message/send، وعميلنا
      يسخد وكلاء A2A خارجيين — **بقائمة سماح صريحة لكل عنوان**
      (قاعدة الخوصصة: لا اتصال صادر إلا بموافقة معلنة).
    * **بلا أي اعتمادية خارجية**: urllib + json فقط.

الاستخدام::

    from src.a2a import build_agent_cards, handle_jsonrpc, A2AClient

    cards = build_agent_cards()          # 106 بطاقة من الجرد
    reply = handle_jsonrpc({"jsonrpc": "2.0", "id": 1,
                            "method": "message/send",
                            "params": {"message": {...}}})
    client = A2AClient("https://peer.example",
                       allowlist=["peer.example"])   # صريح دائمًا
    peer_card = client.fetch_card()
"""

from __future__ import annotations

from src.a2a.card import (
    A2A_PROTOCOL_VERSION,
    AgentCard,
    build_agent_cards,
    build_hub_card,
    card_to_dict,
    validate_card,
)
from src.a2a.client import A2AClient, PrivacyError, a2a_allowlist, host_allowed
from src.a2a.dispatch import (
    JsonRpcError,
    handle_jsonrpc,
    handle_message_send,
)

__all__ = [
    "A2A_PROTOCOL_VERSION",
    "AgentCard",
    "A2AClient",
    "JsonRpcError",
    "PrivacyError",
    "a2a_allowlist",
    "build_agent_cards",
    "build_hub_card",
    "card_to_dict",
    "handle_jsonrpc",
    "handle_message_send",
    "host_allowed",
]
