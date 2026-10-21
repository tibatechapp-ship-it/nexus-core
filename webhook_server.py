import os
"""
Webhook Server - Receives GitHub events
Uses only http.server (no Flask/FastAPI needed)
"""
import hashlib
import hmac
import json
import logging
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("integration.webhook")

#: Max accepted body size (5MB) — reject early
MAX_BODY_BYTES = 5 * 1024 * 1024

#: Hosts that are already local — no exposure to the network.
_LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")


def _resolve_bind_host(secret: str, configured_host: str) -> str:
    """Bind to loopback when the webhook has no secret (C4, defence in depth).

    A missing ``WEBHOOK_SECRET`` means signatures cannot be verified, so an
    unprotected webhook must not be reachable from the network. We force the
    bind address to loopback (and warn) instead of refusing to start, which
    would turn into a crash loop under a container orchestrator.
    """
    if not secret and configured_host not in _LOOPBACK_HOSTS:
        logger.warning(
            "WEBHOOK_SECRET is empty — forcing bind to 127.0.0.1 "
            "(configured host was %r)", configured_host,
        )
        return "127.0.0.1"
    return configured_host


class WebhookHandler(BaseHTTPRequestHandler):
    secret = ""
    on_pr_event = None

    def _json(self, data, code=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _verify(self, body: bytes, sig_header: str) -> bool:
        # C4: fail closed. A missing secret must never accept a request —
        # returning True here (the old behaviour) opened the endpoint to any
        # unauthenticated POST on the network.
        if not self.secret:
            return False
        if not sig_header:
            return False
        expected = "sha256=" + hmac.new(
            self.secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, sig_header)

    def do_POST(self):
        path = self.path
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_BODY_BYTES:
            self._json({"error": "payload too large"}, 413)
            return
        body = self.rfile.read(length) if length else b""

        sig = self.headers.get("X-Hub-Signature-256", "")
        if not self._verify(body, sig):
            logger.warning("invalid webhook signature")
            self._json({"error": "invalid signature"}, 401)
            return

        event = self.headers.get("X-GitHub-Event", "unknown")
        logger.info(f"webhook received: {event}")

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            self._json({"error": "invalid json"}, 400)
            return

        # Handle pull_request events
        if event == "pull_request" and self.on_pr_event:
            action = payload.get("action", "")
            if action in ("opened", "synchronize", "reopened"):
                threading.Thread(
                    target=self.on_pr_event,
                    args=(payload,),
                    daemon=True,
                ).start()

        self._json({"ok": True, "event": event})

    def do_GET(self):
        if self.path == "/health":
            self._json({"ok": True, "service": "novamind-webhook"})
        else:
            self._json({"endpoints": ["/webhook", "/health"]})

    def log_message(self, *args):
        pass  # silence


class WebhookServer:
    def __init__(self, port: int = 8888, secret: str = "",
                 host: str = "127.0.0.1"):
        self.port = port
        self.secret = secret
        self.host = host
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self, on_pr_event=None):
        """Starts the webhook server in a background thread."""
        WebhookHandler.secret = self.secret
        WebhookHandler.on_pr_event = on_pr_event
        host = _resolve_bind_host(self.secret, self.host)

        def _run():
            self.server = HTTPServer((host, self.port),
                                     WebhookHandler)
            logger.info(f"webhook server on {host}:{self.port}")
            self.server.serve_forever()

        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()


# ─── Callback for PR events ──────────────────────────
def handle_pr_event(payload: dict):
    """Called when a PR is opened or updated."""
    try:
        from integration.pr_reviewer import pr_reviewer

        repo = payload["repository"]["full_name"]
        pr_number = payload["pull_request"]["number"]

        logger.info(f"handling PR {repo}#{pr_number}")
        result = pr_reviewer.review_pr(repo, pr_number)
        logger.info(f"review result: {result.get('comments_posted', 0)} comments")

    except Exception as e:
        logger.exception(f"PR event error: {e}")


# Singleton
webhook_server = WebhookServer(
    port=8888,
    secret="",
)

if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO)

    port = int(os.environ.get("WEBHOOK_PORT", "8888"))
    secret = os.environ.get("WEBHOOK_SECRET", "")
    host = os.environ.get("WEBHOOK_HOST", "127.0.0.1")

    server = WebhookServer(port=port, secret=secret, host=host)
    server.start(on_pr_event=handle_pr_event)

    print(f"Webhook server listening on port {port}")
    print(f"Endpoint: http://localhost:{port}/webhook")
    print("Press Ctrl+C to stop")

    try:
        import time
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.stop()
