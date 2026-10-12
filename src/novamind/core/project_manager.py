"""
Project Manager — Manages NovaMind's authorized projects.

Responsibilities:
- Load authorized projects from config/authorized_projects.json
- Track per-project state (memory/projects/<name>.json)
- Enforce permissions and limits
- Provide project discovery API
"""
import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger("core.project_manager")

from novamind.core.paths import NOVAMIND_HOME as BASE_DIR
CONFIG_FILE = BASE_DIR / "config" / "authorized_projects.json"
STATE_DIR = BASE_DIR / "memory" / "projects"
STATE_DIR.mkdir(parents=True, exist_ok=True)


class ProjectManager:
    def __init__(self):
        self.config = self._load_config()
        self.permissions = self.config.get("permissions", {})
        self.limits = self.config.get("limits", {})
        self.agent_info = self.config.get("agent", {})

    def _load_config(self) -> Dict:
        if not CONFIG_FILE.exists():
            logger.error(f"config not found: {CONFIG_FILE}")
            return {"projects": [], "permissions": {}, "limits": {}}
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"config load failed: {e}")
            return {"projects": [], "permissions": {}, "limits": {}}

    def reload(self):
        """Reload config from disk."""
        self.config = self._load_config()
        self.permissions = self.config.get("permissions", {})
        self.limits = self.config.get("limits", {})

    # ─── Project discovery ────────────────────────────
    def all_projects(self) -> List[Dict]:
        return self.config.get("projects", [])

    def enabled_projects(self) -> List[Dict]:
        return [p for p in self.all_projects() if p.get("enabled", False)]

    def get(self, name: str) -> Optional[Dict]:
        for p in self.all_projects():
            if p["name"] == name or p["repo"] == name:
                return p
        return None

    def can(self, permission: str) -> bool:
        """Check if agent has permission."""
        return self.permissions.get(permission, False)

    def can_operate_on(self, project: str, action: str) -> bool:
        """Check if action is allowed on project."""
        p = self.get(project)
        if not p or not p.get("enabled", False):
            return False

        # Map action → project flag
        flags = {
            "review": "auto_review",
            "fix": "auto_fix",
            "test": "auto_test",
            "pr": "auto_pr",
        }
        flag = flags.get(action)
        if flag:
            return p.get(flag, False)
        return True

    # ─── Per-project state ────────────────────────────
    def _state_path(self, project: str) -> Path:
        return STATE_DIR / f"{project}.json"

    def _load_state(self, project: str) -> Dict:
        path = self._state_path(project)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "name": project,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "prs_reviewed": 0,
            "prs_fixed": 0,
            "prs_created": 0,
            "comments_posted": 0,
            "last_activity": None,
            "history": [],
        }

    def _save_state(self, project: str, state: Dict):
        path = self._state_path(project)
        try:
            path.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        except Exception as e:
            logger.error(f"state save failed for {project}: {e}")

    def increment(self, project: str, key: str, amount: int = 1):
        state = self._load_state(project)
        state[key] = state.get(key, 0) + amount
        state["last_activity"] = datetime.now(timezone.utc).isoformat()
        self._save_state(project, state)

    def log_activity(self, project: str, event: str, details: str = ""):
        state = self._load_state(project)
        state.setdefault("history", []).insert(0, {
            "at": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "details": details[:200],
        })
        state["history"] = state["history"][:50]
        state["last_activity"] = datetime.now(timezone.utc).isoformat()
        self._save_state(project, state)

    def get_state(self, project: str) -> Dict:
        return self._load_state(project)

    # ─── Global stats ─────────────────────────────────
    def stats(self) -> Dict:
        total = {"prs_reviewed": 0, "prs_fixed": 0, "prs_created": 0}
        projects_status = []

        for p in self.all_projects():
            state = self._load_state(p["name"])
            for k in total:
                total[k] += state.get(k, 0)
            projects_status.append({
                "name": p["name"],
                "repo": p["repo"],
                "enabled": p.get("enabled", False),
                "priority": p.get("priority", "low"),
                "prs_reviewed": state.get("prs_reviewed", 0),
                "prs_fixed": state.get("prs_fixed", 0),
                "last_activity": state.get("last_activity"),
            })

        return {
            "agent": self.agent_info,
            "total_projects": len(self.all_projects()),
            "enabled_projects": len(self.enabled_projects()),
            "global_totals": total,
            "projects": projects_status,
        }

    # ─── Rate limiting ────────────────────────────────
    def check_rate_limit(self, project: str) -> Dict:
        """Check if project is within its daily/hourly limits."""
        state = self._load_state(project)
        history = state.get("history", [])
        now = datetime.now(timezone.utc)

        day_ago = (now - timedelta(days=1)).isoformat()
        hour_ago = (now - timedelta(hours=1)).isoformat()

        prs_today = sum(1 for h in history
                        if h.get("at", "") >= day_ago and h.get("event") == "pr_created")
        fixes_hour = sum(1 for h in history
                         if h.get("at", "") >= hour_ago and h.get("event") == "fix_applied")

        max_prs = self.limits.get("max_prs_per_repo_per_day", 10)
        max_fixes = self.limits.get("max_fixes_per_hour", 5)

        return {
            "ok": prs_today < max_prs and fixes_hour < max_fixes,
            "prs_today": prs_today,
            "max_prs": max_prs,
            "fixes_hour": fixes_hour,
            "max_fixes": max_fixes,
        }


project_manager = ProjectManager()
