"""عميل A2A الصادر — بقائمة سماح صريحة (قاعدة الخوصصة).

**لا اتصال صادر إلا بضمّان العنوان صراحةً** إلى قائمة السماح — عبر
المعامل ``allowlist`` أو البيئة ``NEXUS_A2A_ALLOWLIST`` (أسماء مضيفين
مفصولة بفواصل). الافتراضي: كل الصادر مرفوض (``PrivacyError``) —
نفس روح ``NEXUS_ALLOW_OPEN`` عندنا.

النقل قابل للحقن (``transport``) — الاختبارات بلا شبكة على الإطلاق.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Callable
from urllib.parse import urlsplit

#: النوع: transport(url, method, body_bytes, headers) -> (status, body_text)
Transport = Callable[[str, str, bytes, dict[str, str]], tuple[int, str]]


class PrivacyError(PermissionError):
    """محاولة اتصال صادر لعنوان خارج قائمة السماح — مرفوضة دائمًا."""


def a2a_allowlist() -> list[str]:
    """اقرأ قائمة السماح من البيئة — مفصولة بفواصل، فارغة = رفض الكل."""
    raw = os.environ.get("NEXUS_A2A_ALLOWLIST", "")
    return [h.strip().lower() for h in raw.split(",") if h.strip()]


def host_allowed(url: str, allowlist: list[str]) -> bool:
    """مضيف العنوان ضمن القائمة؟ (مطابقة حرفية للمضيف — لا wildcards)."""
    if not allowlist:
        return False
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return bool(host) and host in {h.lstrip(".") for h in allowlist}


def _urllib_transport(
    url: str, method: str, body: bytes, headers: dict[str, str],
) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body if method == "POST" else None,
                                 headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return int(getattr(resp, "status", 200)), resp.read().decode("utf-8")


class A2AClient:
    """عميل A2A — جذر خادم + بطاقة تغذي هدف الإرسال (مواصفة حقيقية).

    الدورة: اكتشاف ``<root>/.well-known/agent.json`` → بطاقة تحمل
    ``url`` نقطة الرسائل → إرسال message/send **إلى ذلك العنوان**.
    كل عنوان (الجذر وcard.url معًا) يمرّ بقائمة السماح — لا SSRF
    عبر بطاقة ماكرة.
    """

    def __init__(
        self,
        root: str,
        allowlist: list[str] | None = None,
        transport: Transport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.root = root.rstrip("/")
        self.allowlist = (allowlist if allowlist is not None
                          else a2a_allowlist())
        self.timeout = timeout
        self.transport = transport or _urllib_transport
        self.card: dict[str, Any] | None = None

    def _guard(self, url: str) -> None:
        if not host_allowed(url, self.allowlist):
            raise PrivacyError(
                f"A2A outbound blocked (privacy by default): {url!r} "
                "not in allowlist — enable explicitly via "
                "NEXUS_A2A_ALLOWLIST or the allowlist parameter")

    def _call(self, url: str, method: str, body: bytes,
              headers: dict[str, str]) -> tuple[int, str]:
        self._guard(url)
        return self.transport(url, method, body, headers)

    # ── دورة الاكتشاف والرسالة ────────────────────────────────────
    def fetch_card(self) -> dict[str, Any]:
        """اقرأ بطاقة الوكيل من ``<root>/.well-known/agent.json``."""
        url = self.root + "/.well-known/agent.json"
        status, body = self._call(url, "GET", b"", {"Accept": "application/json"})
        if status != 200:
            raise RuntimeError(f"card fetch failed: HTTP {status}")
        self.card = json.loads(body)
        return self.card

    def _message_endpoint(self) -> str:
        """نقطة الرسائل من البطاقة (لا نه للجذر) — اكتشاف يغذي الإرسال."""
        if self.card is None:
            self.fetch_card()
        assert self.card is not None
        url = str(self.card.get("url", "")).strip()
        if not url.startswith(("http://", "https://")):
            raise RuntimeError("peer card has no valid message url")
        return url

    def send_text(self, text: str, request_id: int | str = 1) -> dict[str, Any]:
        """أرسل رسالة نصية عبر message/send وأعِد رد JSON-RPC كاملًا."""
        url = self._message_endpoint()
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "kind": "message",
                    "messageId": f"nexus-{request_id}",
                    "parts": [{"type": "text", "text": text}],
                },
            },
        }
        body = json.dumps(payload).encode("utf-8")
        status, raw = self._call(url, "POST", body, {
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        if status != 200:
            raise RuntimeError(f"message send failed: HTTP {status}")
        return json.loads(raw)

    def reply_text(self, text: str, request_id: int | str = 1) -> str:
        """إرسال + استخراج نص الرد — استثناء واضح على خطأ JSON-RPC."""
        resp = self.send_text(text, request_id)
        if "error" in resp:
            err = resp["error"]
            raise RuntimeError(
                f"A2A error {err.get('code')}: {err.get('message')}")
        result = resp.get("result", {})
        for p in result.get("parts", []):
            if p.get("type", "text") == "text":
                return str(p.get("text", ""))
        return ""
