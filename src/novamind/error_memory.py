"""Error memory — logs LLM failures for analysis."""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class ErrorMemory:
    """Singleton that stores recent LLM errors for pattern analysis."""
    
    _instance: Optional["ErrorMemory"] = None
    
    def __init__(self, path: Path = None) -> None:
        self.path = path or Path.home() / ".nexus" / "error_memory.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: List[Dict[str, Any]] = []
    
    @classmethod
    def get(cls) -> "ErrorMemory":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def log(
        self,
        error_type: str,
        context: str,
        error_message: str,
        **extra: Any,
    ) -> None:
        """Log an error to memory (append-only)."""
        entry = {
            "ts": time.time(),
            "error_type": error_type,
            "context": context,
            "error_message": error_message[:500],
            **extra,
        }
        self._cache.append(entry)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    
    def recent(self, n: int = 20) -> List[Dict[str, Any]]:
        """Return the n most recent errors."""
        return self._cache[-n:]
    
    def stats(self) -> Dict[str, int]:
        """Return error counts by type."""
        counts: Dict[str, int] = {}
        for e in self._cache:
            counts[e["error_type"]] = counts.get(e["error_type"], 0) + 1
        return counts


def get_error_memory() -> ErrorMemory:
    return ErrorMemory.get()
