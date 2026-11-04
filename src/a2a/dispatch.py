"""مُرسِل رسائل A2A — JSON-RPC 2.0 (message/send غير المتدفق).

العقد (docs/A2A.md):
    * الطلب: ``{"jsonrpc":"2.0","id":…,"method":"message/send",
      "params":{"message":{"role":"user","parts":[{"type":"text",
      "text":…}],"messageId":…,"kind":"message"}}}``
    * الرد: نتيجة برسالة وكيل (``role:"agent"``) أو خطأ JSON-RPC قياسي.
    * أي فشل إدخال = خطأ هيكلي (-32602) لا استثناء متسرب.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from src.a2a.card import A2A_PROTOCOL_VERSION

#: أخطاء JSON-RPC القياسية المستخدمة.
PARSE_ERROR = -32700
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class JsonRpcError(Exception):
    """خطأ JSON-RPC قياسي — يُترجَم إلى رد error لا استثناء شَبكي."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_error(self, request_id: Any = None) -> dict[str, Any]:
        err: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            err["data"] = self.data
        return {"jsonrpc": "2.0", "id": request_id, "error": err}


def _extract_text(message: dict[str, Any]) -> str:
    """اجمع نص أجزاء الرسالة — أجزاء غير نصية تُتجاهل بلا فشل."""
    parts = message.get("parts") or []
    texts = [
        str(p.get("text", ""))
        for p in parts
        if isinstance(p, dict) and p.get("type", "text") == "text"
    ]
    return " ".join(t for t in texts if t)


def _new_message_id() -> str:
    import secrets

    return "msg-" + secrets.token_hex(8)


def handle_message_send(
    params: dict[str, Any],
    text_handler: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """دورة message/send كاملة: تحقّق → معالجة نصية → رسالة وكيل.

    المعالج الافتراضي محلي حتمي (بلا شبكة بلا LLM): إيصال توجيه يعلن
    هوية المنصة ونسخة المواصفة — كافٍ ومناسب لـ conformance وللاكتشاف.
    """
    if not isinstance(params, dict) or "message" not in params:
        raise JsonRpcError(INVALID_PARAMS, "params.message is required")
    message = params.get("message")
    if not isinstance(message, dict):
        raise JsonRpcError(INVALID_PARAMS, "message must be an object")
    parts = message.get("parts")
    if not isinstance(parts, list) or not parts:
        raise JsonRpcError(INVALID_PARAMS, "message.parts must be non-empty")
    text = _extract_text(message)
    if text_handler is None:
        text_handler = _default_text_handler
    try:
        reply_text = text_handler(text)
    except JsonRpcError:
        raise
    except Exception as e:  # fail-closed: لا تسريب استثناءات عبر الشبكة
        raise JsonRpcError(INTERNAL_ERROR, "handler failure") from e
    return {
        "messageId": _new_message_id(),
        "kind": "message",
        "role": "agent",
        "parts": [{"type": "text", "text": reply_text}],
        "contextId": message.get("messageId", ""),
    }


def _default_text_handler(text: str) -> str:
    from src import __version__

    return (
        f"nexus-core {__version__} received your message "
        f"({len(text)} chars) via A2A {A2A_PROTOCOL_VERSION}. "
        "This endpoint is a deterministic local handler; "
        "LLM-backed skills are reached through /api/agent/run."
    )


def handle_jsonrpc(
    request: dict[str, Any],
    text_handler: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """مغلّف JSON-RPC الكامل: message/send + أخطاء الطرق/المعاملات."""
    request_id = request.get("id")
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return JsonRpcError(
            PARSE_ERROR, "jsonrpc must be \"2.0\"",
        ).to_error(request_id)
    method = request.get("method")
    if method == "message/send":
        try:
            result = handle_message_send(
                request.get("params") or {}, text_handler)
        except JsonRpcError as e:
            return e.to_error(request_id)
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    # اكتشاف شائع خارج البطاقة: بعض العملاء يسألون الطريقة مباشرةً.
    if method == "agent/authenticatedExtendedCard":
        return JsonRpcError(
            METHOD_NOT_FOUND, "extended card not implemented",
        ).to_error(request_id)
    return JsonRpcError(
        METHOD_NOT_FOUND, f"method not supported: {method!r}",
    ).to_error(request_id)
