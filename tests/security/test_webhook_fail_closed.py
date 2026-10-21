"""C4 regression guard — webhook_server must fail closed.

The endpoint used to accept ANY request when ``WEBHOOK_SECRET`` was empty
(``_verify`` returned ``True``), and it bound to ``0.0.0.0`` — so an
unauthenticated POST on the network reached ``pr_reviewer.review_pr``.
Same fail-open pattern as C3 (``src/security/access.py``).
"""
import hashlib
import hmac

from webhook_server import WebhookHandler, _resolve_bind_host


def _handler(secret: str) -> WebhookHandler:
    """An unbound handler instance (no socket) with a given secret."""
    handler = WebhookHandler.__new__(WebhookHandler)
    handler.secret = secret
    return handler


def test_verify_rejects_when_secret_empty():
    """Fail-closed: no secret → never accept, even with a plausible signature."""
    assert _handler("")._verify(b"body", "sha256=whatever") is False


def test_verify_rejects_when_sig_missing():
    """Secret set, no signature header → reject."""
    assert _handler("s3cret")._verify(b"body", "") is False


def test_verify_accepts_valid_signature():
    """A correct HMAC signature → accept."""
    secret = "s3cret"
    sig = "sha256=" + hmac.new(
        secret.encode("utf-8"), b"body", hashlib.sha256).hexdigest()
    assert _handler(secret)._verify(b"body", sig) is True


def test_verify_rejects_bad_signature():
    """A wrong signature → reject."""
    assert _handler("s3cret")._verify(b"body", "sha256=deadbeef") is False


def test_bind_loopback_when_no_secret():
    """C4 defence in depth: no secret → force loopback, never expose."""
    assert _resolve_bind_host("", "0.0.0.0") == "127.0.0.1"
    assert _resolve_bind_host("", "127.0.0.1") == "127.0.0.1"
    assert _resolve_bind_host("", "localhost") == "localhost"
    assert _resolve_bind_host("s3cret", "0.0.0.0") == "0.0.0.0"
