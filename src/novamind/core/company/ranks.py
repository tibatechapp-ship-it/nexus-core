"""نظام الرتب العسكرية - Military Ranks."""
from dataclasses import dataclass
from enum import Enum

class Rank(Enum):
    RECRUIT = 0        # مجند (جديد، لم يُدرَّب)
    PRIVATE = 1        # جندي (أكمل التدريب)
    CORPORAL = 2       # عريف
    SERGEANT = 3       # رقيب
    LIEUTENANT = 4     # ملازم
    CAPTAIN = 5        # نقيب
    MAJOR = 6          # رائد
    COLONEL = 7        # عقيد
    GENERAL = 8        # جنرال
    COMMANDANT = 9     # القائد العام

@dataclass
class RankRequirements:
    rank: Rank
    min_tasks: int
    min_success_rate: float
    min_trust_score: float

RANK_REQUIREMENTS = {
    Rank.PRIVATE:    RankRequirements(Rank.PRIVATE, 5, 0.6, 0.5),
    Rank.CORPORAL:   RankRequirements(Rank.CORPORAL, 20, 0.7, 0.6),
    Rank.SERGEANT:   RankRequirements(Rank.SERGEANT, 50, 0.8, 0.7),
    Rank.LIEUTENANT: RankRequirements(Rank.LIEUTENANT, 100, 0.85, 0.8),
    Rank.CAPTAIN:    RankRequirements(Rank.CAPTAIN, 200, 0.9, 0.85),
    Rank.MAJOR:      RankRequirements(Rank.MAJOR, 400, 0.92, 0.9),
    Rank.COLONEL:    RankRequirements(Rank.COLONEL, 800, 0.95, 0.95),
    Rank.GENERAL:    RankRequirements(Rank.GENERAL, 1500, 0.97, 0.97),
}

def can_promote(rank, tasks, success_rate, trust):
    next_rank = Rank(rank.value + 1) if rank.value < Rank.COMMANDANT.value else None
    if not next_rank: return False
    req = RANK_REQUIREMENTS.get(next_rank)
    if not req: return False
    return (tasks >= req.min_tasks and
            success_rate >= req.min_success_rate and
            trust >= req.min_trust_score)
