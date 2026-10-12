"""ToolRegistry — تسجيل وتبادل الأدوات."""
from typing import Dict, Any, Callable, Optional
import logging

log = logging.getLogger("ToolRegistry")


class ToolRegistry:
    """مركز تسجيل الأدوات."""

    def __init__(self):
        self._tools: Dict[str, dict] = {}

    def register(self, name: str, func: Callable, description: str = "",
                 agent: Optional[str] = None):
        """يسجّل أداة."""
        self._tools[name] = {
            "func": func,
            "description": description,
            "agent": agent,
        }

    def get(self, name: str) -> Optional[Callable]:
        entry = self._tools.get(name)
        return entry["func"] if entry else None

    def list_all(self) -> Dict[str, dict]:
        return dict(self._tools)

    def list_by_agent(self, agent: str) -> Dict[str, dict]:
        return {n: t for n, t in self._tools.items()
                if t["agent"] == agent}

    def search(self, keyword: str) -> Dict[str, dict]:
        kw = keyword.lower()
        return {
            n: t for n, t in self._tools.items()
            if kw in n.lower() or kw in t["description"].lower()
        }


_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
