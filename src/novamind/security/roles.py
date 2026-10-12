"""RoleRegistry — سجل الأدوار والفريق."""
from typing import Dict, List, Optional
import logging

log = logging.getLogger("Roles")


# ═══ الأدوار المتاحة ═══
ROLES = {
    # Executive
    "executive": {
        "ar": "الإدارة التنفيذية",
        "levels": [3, 4, 5],
        "responsibilities": ["تخطيط", "قرارات", "تنسيق"],
    },
    # Research
    "researcher": {
        "ar": "البحث",
        "levels": [2, 3],
        "responsibilities": ["بحث", "تحليل", "توثيق"],
    },
    # Engineering
    "engineer": {
        "ar": "الهندسة",
        "levels": [1, 2, 3],
        "responsibilities": ["بناء", "اختبار", "نشر"],
    },
    # Quality
    "quality": {
        "ar": "الجودة",
        "levels": [2, 3],
        "responsibilities": ["مراجعة", "اختبار", "تدقيق"],
    },
    # Automation
    "automation": {
        "ar": "الأتمتة",
        "levels": [2],
        "responsibilities": ["مراقبة", "تنفيذ"],
    },
}


class TeamRegistry:
    """سجل الفريق الكامل."""

    def __init__(self):
        self.members: Dict[str, dict] = {}
        self.by_role: Dict[str, List[str]] = {}
        self.by_level: Dict[int, List[str]] = {}

    def add(self, name: str, role: str, level: int,
            capabilities: List[str], agent):
        """أضف عضو."""
        self.members[name] = {
            "name": name,
            "role": role,
            "level": level,
            "capabilities": capabilities,
            "agent": agent,
        }
        self.by_role.setdefault(role, []).append(name)
        self.by_level.setdefault(level, []).append(name)

    def get(self, name: str) -> Optional[dict]:
        return self.members.get(name)

    def get_by_role(self, role: str) -> List[dict]:
        names = self.by_role.get(role, [])
        return [self.members[n] for n in names]

    def get_by_level(self, level: int) -> List[dict]:
        names = self.by_level.get(level, [])
        return [self.members[n] for n in names]

    def find_for_capability(self, capability: str) -> List[dict]:
        """ابحث عن أعضاء يمتلكون قدرة."""
        matches = []
        for m in self.members.values():
            if capability in m["capabilities"]:
                matches.append(m)
        return matches

    def summary(self) -> dict:
        """ملخص الفريق."""
        return {
            "total": len(self.members),
            "by_role": {r: len(n) for r, n in self.by_role.items()},
            "by_level": {l: len(n) for l, n in self.by_level.items()},
        }

    def list_all(self) -> list:
        """اعرض كل الأعضاء."""
        return sorted(self.members.values(), key=lambda m: -m["level"])


_registry: Optional[TeamRegistry] = None


def get_team_registry() -> TeamRegistry:
    global _registry
    if _registry is None:
        _registry = TeamRegistry()
    return _registry
