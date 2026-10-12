"""MilitaryID — نظام الهوية العسكرية"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
from pathlib import Path
import hashlib
import json
import time
import re
import logging

logger = logging.getLogger("military_id")


class Rank(Enum):
    RECRUIT = (1, "مجنّد")
    SOLDIER = (2, "جندي")
    CORPORAL = (3, "عريف")
    SERGEANT = (4, "رقيب")
    STAFF_SERGEANT = (5, "رقيب أول")
    LIEUTENANT = (6, "ملازم")
    CAPTAIN = (7, "نقيب")
    MAJOR = (8, "رائد")
    LIEUTENANT_COLONEL = (9, "مقدم")
    COLONEL = (10, "عقيد")
    BRIGADIER = (11, "عميد")
    MAJOR_GENERAL = (12, "لواء")
    LIEUTENANT_GENERAL = (13, "فريق")
    GENERAL = (14, "فريق أول")
    FIELD_MARSHAL = (15, "مشير")
    
    def __init__(self, level: int, arabic_name: str):
        self.level = level
        self.arabic_name = arabic_name
    
    @property
    def category(self) -> str:
        if self.level <= 5: return "soldier"
        elif self.level <= 10: return "officer"
        return "command"
    
    @property
    def category_arabic(self) -> str:
        return {"soldier": "عسكري", "officer": "ضابط", "command": "قيادة"}[self.category]


class RankHierarchy:
    @staticmethod
    def can_command(c: Rank, s: Rank) -> bool:
        return c.level > s.level
    
    @staticmethod
    def next_rank(current: Rank) -> Optional[Rank]:
        for rank in Rank:
            if rank.level == current.level + 1:
                return rank
        return None
    
    @staticmethod
    def promotion_requirements(rank: Rank) -> Dict:
        next_r = RankHierarchy.next_rank(rank)
        if not next_r: return {}
        return {
            "from": rank.name, "to": next_r.name,
            "min_missions": rank.level * 10,
            "min_success_rate": 0.85,
            "min_training_hours": rank.level * 20,
        }


class Branch(Enum):
    CODER = ("CODER", "سلاح البرمجة")
    SECURITY = ("SEC", "سلاح الأمن")
    ANALYZER = ("ANLZ", "سلاح التحليل")
    FIXER = ("FIX", "سلاح الإصلاح")
    TESTER = ("TEST", "سلاح الاختبار")
    LEARNER = ("LRN", "سلاح التعلم")
    DEVOPS = ("OPS", "سلاح العمليات")
    QUALITY = ("QA", "سلاح الجودة")
    DATABASE = ("DB", "سلاح البيانات")
    FRONTEND = ("FE", "سلاح الواجهات")
    BACKEND = ("BE", "سلاح الخوادم")
    AI = ("AI", "سلاح الذكاء")
    ARCHITECTURE = ("ARCH", "سلاح الهندسة")
    TRAINER = ("TRN", "سلاح التدريب")
    COMMANDER = ("CMD", "القيادة العليا")
    MONITOR = ("MON", "سلاح المراقبة")
    
    def __init__(self, code: str, arabic_name: str):
        self.code = code
        self.arabic_name = arabic_name


class Clearance(Enum):
    PUBLIC = (1, "عام")
    INTERNAL = (2, "داخلي")
    RESTRICTED = (3, "مقيد")
    CONFIDENTIAL = (4, "خاص")
    SECRET = (5, "سري")
    TOP_SECRET = (6, "سري للغاية")
    
    def __init__(self, level: int, arabic_name: str):
        self.level = level
        self.arabic_name = arabic_name


class Fingerprint:
    @staticmethod
    def generate(name: str, branch: Branch, rank: Rank, created_at: float, attrs=None) -> str:
        data = {
            "name": name, "branch": branch.code, "rank": rank.name,
            "created_at": f"{created_at:.6f}", "attrs": attrs or {},
        }
        raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]
    
    @staticmethod
    def short(fp: str) -> str:
        return f"{fp[:4]}-{fp[4:8]}" if len(fp) >= 8 else fp


@dataclass
class MilitaryID:
    full_id: str
    prefix: str
    branch: str
    serial: int
    revision: str
    check_digit: str
    
    @classmethod
    def create(cls, branch: Branch, serial: int, revision: str = "A") -> "MilitaryID":
        if serial < 1 or serial > 9999:
            raise ValueError(f"Serial must be 1-9999")
        if not re.match(r'^[A-Z]$', revision):
            raise ValueError(f"Revision must be A-Z")
        prefix = "NM"
        no_check = f"{prefix}-{branch.code}-{serial:04d}-{revision}"
        check = cls._compute_check_digit(no_check)
        return cls(
            full_id=f"{no_check}{check}",
            prefix=prefix, branch=branch.code,
            serial=serial, revision=revision, check_digit=check,
        )
    
    @staticmethod
    def _compute_check_digit(s: str) -> str:
        h = hashlib.sha256(s.encode()).hexdigest()
        return chr(ord('A') + (int(h[:4], 16) % 26))
    
    @classmethod
    def parse(cls, full_id: str) -> Optional["MilitaryID"]:
        m = re.match(r'^(NM)-([A-Z]+)-(\d{4})-([A-Z])([A-Z])$', full_id)
        if not m: return None
        return cls(
            full_id=full_id, prefix=m.group(1), branch=m.group(2),
            serial=int(m.group(3)), revision=m.group(4), check_digit=m.group(5),
        )
    
    @classmethod
    def verify(cls, full_id: str) -> bool:
        p = cls.parse(full_id)
        if not p: return False
        no_check = f"{p.prefix}-{p.branch}-{p.serial:04d}-{p.revision}"
        return cls._compute_check_digit(no_check) == p.check_digit
    
    def __str__(self): return self.full_id


class IDGenerator:
    def __init__(self, state_file: Optional[Path] = None):
        self.state_file = state_file
        self.counters: Dict[str, int] = {}
        self._load_state()
    
    def _load_state(self):
        if self.state_file and self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                self.counters = data.get("counters", {})
            except Exception:
                pass
    
    def _save_state(self):
        if self.state_file:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps({"counters": self.counters}, indent=2))
    
    def generate(self, branch: Branch, revision: str = "A") -> MilitaryID:
        self.counters[branch.code] = self.counters.get(branch.code, 0) + 1
        mid = MilitaryID.create(branch, self.counters[branch.code], revision)
        self._save_state()
        return mid


@dataclass
class AgentProfile:
    military_id: MilitaryID
    name: str
    branch: Branch
    rank: Rank
    clearance: Clearance
    fingerprint: str
    created_at: float
    promoted_at: float = 0.0
    missions_completed: int = 0
    missions_failed: int = 0
    training_hours: int = 0
    commanding_officer: Optional[str] = None
    subordinates: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    status: str = "active"
    promotions: List[Dict] = field(default_factory=list)
    awards: List[Dict] = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        total = self.missions_completed + self.missions_failed
        return self.missions_completed / total if total > 0 else 1.0
    
    def to_dict(self) -> Dict:
        return {
            "military_id": self.military_id.full_id,
            "name": self.name, "branch": self.branch.name,
            "rank": self.rank.name, "clearance": self.clearance.name,
            "fingerprint": self.fingerprint,
            "created_at": self.created_at,
            "missions_completed": self.missions_completed,
            "missions_failed": self.missions_failed,
            "skills": self.skills, "status": self.status,
        }
    
    def to_card(self) -> str:
        return "\n".join([
            "╔════════════════════════════════════════════════╗",
            f"║ الرقم: {self.military_id.full_id:<37} ║",
            f"║ الاسم: {self.name:<37} ║",
            f"║ الفرع: {self.branch.arabic_name:<37} ║",
            f"║ الرتبة: {self.rank.arabic_name:<36} ║",
            f"║ البصمة: {Fingerprint.short(self.fingerprint):<36} ║",
            "╚════════════════════════════════════════════════╝",
        ])


class PersonnelRegistry:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir) / ".nova" / "personnel"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.profiles: Dict[str, AgentProfile] = {}
        self.id_generator = IDGenerator(self.base_dir / "id_state.json")
        self._load_profiles()
    
    def _load_profiles(self):
        for f in self.base_dir.glob("*.json"):
            if f.name == "id_state.json": continue
            try:
                data = json.loads(f.read_text())
                mid = MilitaryID.parse(data["military_id"])
                if not mid: continue
                profile = AgentProfile(
                    military_id=mid, name=data["name"],
                    branch=Branch[data["branch"]] if data["branch"] in [b.name for b in Branch] else Branch.CODER,
                    rank=Rank[data["rank"]] if data["rank"] in [r.name for r in Rank] else Rank.RECRUIT,
                    clearance=Clearance[data["clearance"]] if data["clearance"] in [c.name for c in Clearance] else Clearance.INTERNAL,
                    fingerprint=data["fingerprint"],
                    created_at=data["created_at"],
                    missions_completed=data.get("missions_completed", 0),
                    missions_failed=data.get("missions_failed", 0),
                    skills=data.get("skills", []),
                    status=data.get("status", "active"),
                )
                self.profiles[mid.full_id] = profile
            except Exception:
                pass
    
    def enlist(self, name: str, branch: Branch, rank: Rank = Rank.RECRUIT,
               clearance: Clearance = Clearance.INTERNAL, skills=None) -> AgentProfile:
        mid = self.id_generator.generate(branch)
        created_at = time.time()
        fp = Fingerprint.generate(name, branch, rank, created_at)
        profile = AgentProfile(
            military_id=mid, name=name, branch=branch, rank=rank,
            clearance=clearance, fingerprint=fp, created_at=created_at,
            skills=skills or [],
        )
        self.profiles[mid.full_id] = profile
        self._save_profile(profile)
        return profile
    
    def _save_profile(self, profile: AgentProfile):
        f = self.base_dir / f"{profile.military_id.full_id}.json"
        f.write_text(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False, default=str))
    
    def get(self, mid: str) -> Optional[AgentProfile]:
        return self.profiles.get(mid)
    
    def promote(self, mid: str, new_rank: Rank, reason: str = "") -> bool:
        p = self.profiles.get(mid)
        if not p: return False
        old = p.rank
        p.rank = new_rank
        p.promoted_at = time.time()
        p.promotions.append({"from": old.name, "to": new_rank.name, "at": time.time(), "reason": reason})
        self._save_profile(p)
        return True
    
    def stats(self) -> Dict:
        by_branch = {}
        for p in self.profiles.values():
            by_branch[p.branch.code] = by_branch.get(p.branch.code, 0) + 1
        return {"total": len(self.profiles), "by_branch": by_branch}
