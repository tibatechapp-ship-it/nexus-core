"""Audit Trail - HMAC chain, tamper-proof."""
import hashlib
import hmac
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Any

logger = logging.getLogger("Audit")

SECRET = b"novamind-audit-master-key-2026"


class AuditTrail:
    def __init__(self, log_file: str = "data/company/audit.log"):
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        self.log_file = log_file
        self._load()

    def _load(self):
        self.entries = []
        if Path(self.log_file).exists():
            with open(self.log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self.entries.append(json.loads(line))
                        except Exception:
                            pass
        self.last_hash = self.entries[-1]["hash"] if self.entries else "GENESIS"

    def _compute_hash(self, payload: str, prev_hash: str) -> str:
        data = prev_hash + ":" + payload
        return hmac.new(SECRET, data.encode(), hashlib.sha256).hexdigest()

    def record(self, event_type, actor, data):
        entry = {
            "seq": len(self.entries) + 1,
            "time": time.time(),
            "event": event_type,
            "actor": actor,
            "data": data,
            "prev_hash": self.last_hash,
        }
        payload = json.dumps(
            {k: v for k, v in entry.items() if k != "hash"},
            sort_keys=True, ensure_ascii=False
        )
        entry["hash"] = self._compute_hash(payload, self.last_hash)

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        self.entries.append(entry)
        self.last_hash = entry["hash"]
        return entry

    def verify_chain(self):
        prev = "GENESIS"
        for i, entry in enumerate(self.entries):
            payload = json.dumps(
                {k: v for k, v in entry.items() if k != "hash"},
                sort_keys=True, ensure_ascii=False
            )
            expected = self._compute_hash(payload, prev)
            if not hmac.compare_digest(expected, entry["hash"]):
                return {"valid": False, "broken_at": i + 1}
            prev = entry["hash"]
        return {"valid": True, "entries": len(self.entries)}

    def recent(self, limit: int = 10):
        return self.entries[-limit:]
