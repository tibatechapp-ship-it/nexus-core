"""Session Manager — حفظ واستئناف الجلسات.

يحفظ جلسات العمل في ~/.config/nexus/sessions/
كل جلسة تحتوي: ID, title, created_at, messages, agent, backend, metadata.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

__all__ = ["Session", "SessionManager"]

SESSIONS_DIR = Path.home() / ".config" / "nexus" / "sessions"


@dataclass
class Session:
    """جلسة عمل واحدة."""
    id: str
    title: str
    created_at: str
    updated_at: str
    agent: str = "analyst"
    backend: str = "ollama"
    messages: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def new(cls, title: str = "New session", agent: str = "analyst") -> "Session":
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            id=f"ses_{uuid.uuid4().hex[:16]}",
            title=title,
            created_at=now,
            updated_at=now,
            agent=agent,
        )

    def add_message(self, role: str, content: str, **extra: Any) -> None:
        """يضيف رسالة ويحدّث updated_at."""
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **extra,
        })
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Session":
        return cls(**data)


class SessionManager:
    """إدارة كل الجلسات."""

    def __init__(self, base_dir: Path = SESSIONS_DIR) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.json"

    def create(self, title: str = "New session", agent: str = "analyst") -> Session:
        """ينشئ جلسة جديدة ويحفظها."""
        session = Session.new(title=title, agent=agent)
        self.save(session)
        return session

    def save(self, session: Session) -> Path:
        """يحفظ الجلسة."""
        path = self._path(session.id)
        path.write_text(
            json.dumps(session.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def load(self, session_id: str) -> Session | None:
        """يحمّل جلسة بالمعرف."""
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Session.from_dict(data)
        except Exception:
            return None

    def list_sessions(self, limit: int = 50) -> list[Session]:
        """يعرض الجلسات مرتبة بالتاريخ."""
        sessions: list[Session] = []
        for path in sorted(self.base_dir.glob("ses_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                sessions.append(Session.from_dict(data))
            except Exception:
                continue
            if len(sessions) >= limit:
                break
        return sessions

    def delete(self, session_id: str) -> bool:
        """يحذف جلسة."""
        path = self._path(session_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def latest(self) -> Session | None:
        """يعيد آخر جلسة."""
        sessions = self.list_sessions(limit=1)
        return sessions[0] if sessions else None

    def export(self, session_id: str, dest: Path) -> Path:
        """يصدّر جلسة إلى ملف."""
        session = self.load(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        dest.write_text(
            json.dumps(session.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return dest
