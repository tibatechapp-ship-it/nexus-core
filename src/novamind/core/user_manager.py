"""
UserManager - Multi-user support
- Each user has: token, chat_id, memory, stats
- Isolated per user
"""
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional
import os

logger = logging.getLogger("core.user_manager")


USERS_FILE = Path(os.environ.get("NOVAMIND_HOME", str(Path(__file__).resolve().parent.parent))) / "memory/users.json"


class UserManager:
    def __init__(self):
        self.file = USERS_FILE
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self) -> Dict:
        if self.file.exists():
            try:
                return json.loads(self.file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"users": {}, "next_id": 1}

    def _save(self):
        try:
            self.file.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"user save failed: {e}")

    def register(self, tg_id: int, github_token: str = "",
                 name: str = "") -> Dict:
        """Registers a new user."""
        key = str(tg_id)

        if key not in self.data["users"]:
            user_id = "U" + str(self.data["next_id"])
            self.data["next_id"] += 1
            self.data["users"][key] = {
                "id": user_id,
                "tg_id": tg_id,
                "name": name,
                "github_token": github_token,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "memory_dir": f"{os.environ.get('NOVAMIND_HOME', str(Path(__file__).resolve().parent.parent))}/memory/{user_id}",
                "repos": [],
                "stats": {"reviews": 0, "fixes": 0, "tasks": 0},
            }
            Path(self.data["users"][key]["memory_dir"]).mkdir(
                parents=True, exist_ok=True
            )
            self._save()
            logger.info(f"registered user {key} -> {user_id}")

        return self.data["users"][key]

    def get(self, tg_id: int) -> Optional[Dict]:
        return self.data["users"].get(str(tg_id))

    def update_token(self, tg_id: int, github_token: str):
        user = self.get(tg_id)
        if user:
            user["github_token"] = github_token
            self._save()

    def add_repo(self, tg_id: int, repo: str):
        user = self.get(tg_id)
        if user and repo not in user.get("repos", []):
            user.setdefault("repos", []).append(repo)
            self._save()

    def increment_stat(self, tg_id: int, key: str, amount: int = 1):
        user = self.get(tg_id)
        if user:
            user["stats"][key] = user["stats"].get(key, 0) + amount
            self._save()

    def list_users(self) -> List[Dict]:
        return list(self.data["users"].values())

    def stats(self) -> Dict:
        return {
            "total_users": len(self.data["users"]),
            "total_reviews": sum(u["stats"].get("reviews", 0) for u in self.data["users"].values()),
            "total_fixes": sum(u["stats"].get("fixes", 0) for u in self.data["users"].values()),
        }


user_manager = UserManager()
