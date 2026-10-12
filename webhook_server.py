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
        if not self.secret:
            return True  # no secret → skip
        if not sig_header:
            return False
        expected = "sha256=" + hmac.new(
            self.secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, sig_header)

    def do_POST(self):
        path = self.path
        length = int(self.headers.get("Content-Length", 0))
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
    def __init__(self, port: int = 8888, secret: str = ""):
        self.port = port
        self.secret = secret
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self, on_pr_event=None):
        """Starts the webhook server in a background thread."""
        WebhookHandler.secret = self.secret
        WebhookHandler.on_pr_event = on_pr_event

        def _run():
            self.server = HTTPServer(("0.0.0.0", self.port),
                                     WebhookHandler)
            logger.info(f"webhook server on port {self.port}")
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

    server = WebhookServer(port=port, secret=secret)
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
