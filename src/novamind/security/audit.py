"""AuditLog — JSONL Event Logging."""
import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger("AuditLog")


class AuditLog:
    def __init__(self, log_file="/var/log/hive/audit.jsonl"):
        self.file = Path(log_file)
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
