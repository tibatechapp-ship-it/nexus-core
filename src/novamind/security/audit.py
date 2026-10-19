"""AuditLog — JSONL Event Logging."""
import json
import logging
import os
from datetime import datetime
from pathlib import Path

log = logging.getLogger("AuditLog")

DEFAULT_LOG_FILE = "/var/log/hive/audit.jsonl"


def _audit_path() -> Path:
    """مسار سجلّ التدقيق: env override وإلا جذر قابل للكتابة (انظر novamind.paths)."""
    override = os.environ.get("AUDIT_LOG_FILE")
    if override:
        return Path(override)
    from ..paths import writable_path

    return writable_path(
        "audit.jsonl",
        preferred=(str(Path(DEFAULT_LOG_FILE).parent), "/var/tmp/hive"),
    )


class AuditLog:
    def __init__(self, log_file=None):
        self.file = Path(log_file) if log_file else _audit_path()
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.total_events = 0

    def log(self, event_type, data):
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "data": data,
        }
        try:
            with self.file.open("a") as f:
                f.write(json.dumps(event, default=str) + "\n")
            self.total_events += 1
        except Exception as e:
            log.error("Audit write failed: " + str(e))

    def stats(self):
        return {
            "file": str(self.file),
            "total_events": self.total_events,
        }


_audit = None


def get_audit():
    global _audit
    if _audit is None:
        _audit = AuditLog()
    return _audit
