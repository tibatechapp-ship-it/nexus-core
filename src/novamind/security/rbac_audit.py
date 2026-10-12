"""RBAC Audit Trail — تسجيل كل قرارات الصلاحيات.

كل قرار:
    - agent_name
    - permission
    - decision (allowed/denied)
    - timestamp
    - context

يُخزَّن في: /var/log/hive/rbac_audit.jsonl
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("rbac.audit")


class RBACAudit:
    """Audit trail for RBAC decisions."""

    def __init__(self, log_file: Optional[str] = None):
        default_path = os.environ.get(
            "RBAC_AUDIT_LOG",
            "/var/log/hive/rbac_audit.jsonl"
        )
        self.file = Path(log_file or default_path)
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            # Fallback: local log
            self.file = Path("/tmp/rbac_audit.jsonl")
            logger.warning("Cannot write to %s, using /tmp", default_path)

        self.total_events = 0
        self.denied_events = 0

    def log(
        self,
        agent_name: str,
        permission: str,
        allowed: bool,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """سجّل قرار صلاحية."""
        event = {
            "ts": datetime.now().isoformat(),
            "agent": agent_name,
            "permission": permission,
            "allowed": allowed,
            "context": context or {},
        }
        try:
            with self.file.open("a") as f:
                f.write(json.dumps(event, default=str) + "\n")
            self.total_events += 1
            if not allowed:
                self.denied_events += 1
        except Exception as e:
            logger.error("RBAC audit write failed: %s", e)

    def stats(self) -> Dict[str, Any]:
        return {
            "total": self.total_events,
            "denied": self.denied_events,
            "allowed": self.total_events - self.denied_events,
            "file": str(self.file),
        }


# ─── Singleton ───
_audit: Optional[RBACAudit] = None


def get_rbac_audit() -> RBACAudit:
    global _audit
    if _audit is None:
        _audit = RBACAudit()
    return _audit


__all__ = ["RBACAudit", "get_rbac_audit"]
