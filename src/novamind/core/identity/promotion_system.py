"""PromotionSystem — نظام الترقية الصارم"""
from dataclasses import dataclass
from typing import Dict
from enum import Enum
import logging

from .military_id import Rank, RankHierarchy

logger = logging.getLogger("promotion")


class PromotionVerdict(Enum):
    PROMOTED = "promoted"
    NOT_READY = "not_ready"
    BLOCKED = "blocked"
    DEMOTED = "demoted"


@dataclass
class PerformanceMetrics:
    missions_completed: int = 0
    missions_failed: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    avg_response_time: float = 10.0
    target_response_time: float = 5.0
    accuracy: float = 0.0
    hallucination_score: int = 0
    
    @property
    def mission_success_rate(self) -> float:
        total = self.missions_completed + self.missions_failed
        return self.missions_completed / total if total > 0 else 0.0
    
    @property
    def test_success_rate(self) -> float:
        total = self.tests_passed + self.tests_failed
        return self.tests_passed / total if total > 0 else 0.0
    
    @property
    def speed_score(self) -> float:
        if self.avg_response_time <= self.target_response_time:
            return 1.0
        max_t = self.target_response_time * 3
        if self.avg_response_time >= max_t:
            return 0.0
        return 1.0 - (self.avg_response_time - self.target_response_time) / (max_t - self.target_response_time)
    
    @property
    def hallucination_normalized(self) -> float:
        return max(0.0, 1.0 - self.hallucination_score / 50)


class PromotionSystem:
    WEIGHTS = {"missions": 0.30, "tests": 0.30, "speed": 0.15, "accuracy": 0.25}
    
    MIN_THRESHOLDS = {
        Rank.RECRUIT: 0.30, Rank.SOLDIER: 0.40, Rank.CORPORAL: 0.50,
        Rank.SERGEANT: 0.55, Rank.STAFF_SERGEANT: 0.60,
        Rank.LIEUTENANT: 0.65, Rank.CAPTAIN: 0.70, Rank.MAJOR: 0.75,
        Rank.LIEUTENANT_COLONEL: 0.80, Rank.COLONEL: 0.85,
        Rank.BRIGADIER: 0.88, Rank.MAJOR_GENERAL: 0.90,
        Rank.LIEUTENANT_GENERAL: 0.92, Rank.GENERAL: 0.95,
        Rank.FIELD_MARSHAL: 0.98,
    }
    
    HALLUCINATION_LIMITS = {
        Rank.RECRUIT: 20, Rank.SOLDIER: 15, Rank.CORPORAL: 10,
        Rank.SERGEANT: 8, Rank.STAFF_SERGEANT: 6,
        Rank.LIEUTENANT: 5, Rank.CAPTAIN: 4, Rank.MAJOR: 3,
        Rank.LIEUTENANT_COLONEL: 2, Rank.COLONEL: 1,
        Rank.BRIGADIER: 0, Rank.MAJOR_GENERAL: 0,
        Rank.LIEUTENANT_GENERAL: 0, Rank.GENERAL: 0,
        Rank.FIELD_MARSHAL: 0,
    }
    
    def __init__(self, registry, guard):
        self.registry = registry
        self.guard = guard
    
    def evaluate(self, mid: str, metrics: PerformanceMetrics) -> Dict:
        profile = self.registry.get(mid)
        if not profile:
            return {"error": "not_found"}
        
        hall = self.guard.get_record(mid)
        metrics.hallucination_score = hall.weighted_score
        
        s_m = metrics.mission_success_rate
        s_t = metrics.test_success_rate
        s_s = metrics.speed_score
        s_a = metrics.accuracy * metrics.hallucination_normalized
        
        final = (
            s_m * self.WEIGHTS["missions"] +
            s_t * self.WEIGHTS["tests"] +
            s_s * self.WEIGHTS["speed"] +
            s_a * self.WEIGHTS["accuracy"]
        )
        final = self.guard.apply_score_penalty(mid, final)
        
        next_r = RankHierarchy.next_rank(profile.rank)
        min_req = self.MIN_THRESHOLDS.get(next_r, 1.0) if next_r else 1.0
        hall_limit = self.HALLUCINATION_LIMITS.get(profile.rank, 0)
        
        return {
            "military_id": mid, "name": profile.name,
            "current_rank": profile.rank.name,
            "current_rank_arabic": profile.rank.arabic_name,
            "next_rank": next_r.name if next_r else None,
            "next_rank_arabic": next_r.arabic_name if next_r else None,
            "sub_scores": {
                "missions": round(s_m, 3), "tests": round(s_t, 3),
                "speed": round(s_s, 3), "accuracy": round(s_a, 3),
            },
            "final_score": round(final, 3),
            "min_required": round(min_req, 3),
            "hallucination": {
                "score": hall.weighted_score,
                "limit": hall_limit,
                "is_ok": hall.weighted_score <= hall_limit,
                "trust": round(hall.trust_level, 3),
                "trust_level": round(hall.trust_level, 3),  # alias للتوافق
                "is_frozen": hall.is_frozen,
                "should_retire": hall.should_retire,
            },
        }
    
    def decide_promotion(self, mid: str, metrics: PerformanceMetrics) -> Dict:
        ev = self.evaluate(mid, metrics)
        if "error" in ev: return ev
        
        profile = self.registry.get(mid)
        hall = self.guard.get_record(mid)
        
        if hall.should_retire:
            return {**ev, "verdict": PromotionVerdict.BLOCKED.value,
                    "reason": "تجاوز حد الهلوسة", "action": "retire"}
        if hall.is_frozen:
            return {**ev, "verdict": PromotionVerdict.BLOCKED.value,
                    "reason": "مجمّد — إعادة تدريب", "action": "retrain"}
        
        limit = self.HALLUCINATION_LIMITS.get(profile.rank, 0)
        if hall.weighted_score > limit:
            return {**ev, "verdict": PromotionVerdict.NOT_READY.value,
                    "reason": f"تجاوز حد هلوسة الرتبة ({hall.weighted_score}>{limit})"}
        
        if ev["final_score"] < ev["min_required"]:
            return {**ev, "verdict": PromotionVerdict.NOT_READY.value,
                    "reason": f"الدرجة أقل بـ {ev['min_required']-ev['final_score']:.3f}"}
        
        next_r = RankHierarchy.next_rank(profile.rank)
        if next_r and self.HALLUCINATION_LIMITS.get(next_r, 1) == 0:
            if hall.weighted_score > 0:
                return {**ev, "verdict": PromotionVerdict.NOT_READY.value,
                        "reason": f"{next_r.arabic_name} تتطلب صفر هلوسة"}
        
        self.registry.promote(mid, next_r, f"ترقية — {ev['final_score']}")
        return {**ev, "verdict": PromotionVerdict.PROMOTED.value,
                "reason": "اجتاز كل الشروط", "action": "promoted",
                "new_rank_arabic": next_r.arabic_name}
    
    def performance_card(self, mid: str, metrics: PerformanceMetrics) -> str:
        e = self.evaluate(mid, metrics)
        if "error" in e: return f"❌ {e['error']}"
        s, h = e["sub_scores"], e["hallucination"]
        return "\n".join([
            "╔════════════════════════════════════════════╗",
            f"║ 📊 {e['name']:<39} ║",
            f"║ الرقم: {e['military_id']:<34} ║",
            f"║ الرتبة: {e['current_rank_arabic']:<33} ║",
            "╠════════════════════════════════════════════╣",
            f"║ 1. الأداء:       {s['missions']:.3f}  (30%)         ║",
            f"║ 2. الاختبارات:   {s['tests']:.3f}  (30%)         ║",
            f"║ 3. السرعة:       {s['speed']:.3f}  (15%)         ║",
            f"║ 4. الدقة+الهلوسة:{s['accuracy']:.3f}  (25%)         ║",
            "╠════════════════════════════════════════════╣",
            f"║ الدرجة النهائية: {e['final_score']:.3f}                 ║",
            f"║ المطلوب للترقية: {e['min_required']:.3f}                 ║",
            f"║ 🚨 الهلوسة: {h['score']}/{h['limit']}  ثقة={h['trust']*100:.0f}%      ║",
            "╚════════════════════════════════════════════╝",
        ])
