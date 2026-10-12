"""Daily Targets - أهداف يومية لكل تخصص."""
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime

logger = logging.getLogger("Targets")

DAILY_TARGETS = {
    "coder": {"min_tasks": 10, "target_tasks": 20, "bonus_tasks": 30,
        "min_success_rate": 0.75, "target_success_rate": 0.85, "bonus_success_rate": 0.95,
        "max_avg_time": 30, "max_hallucinations": 1,
        "rewards": {"meet_target": 20, "exceed_target": 50, "perfect": 100,
                    "miss_min": -20, "hallucination": -30}},
    "fixer": {"min_tasks": 8, "target_tasks": 15, "bonus_tasks": 25,
        "min_success_rate": 0.70, "target_success_rate": 0.80, "bonus_success_rate": 0.90,
        "max_avg_time": 40, "max_hallucinations": 1,
        "rewards": {"meet_target": 20, "exceed_target": 50, "perfect": 100,
                    "miss_min": -20, "hallucination": -30}},
    "tester": {"min_tasks": 12, "target_tasks": 25, "bonus_tasks": 35,
        "min_success_rate": 0.80, "target_success_rate": 0.90, "bonus_success_rate": 0.95,
        "max_avg_time": 25, "max_hallucinations": 0,
        "rewards": {"meet_target": 20, "exceed_target": 50, "perfect": 100,
                    "miss_min": -20, "hallucination": -30}},
    "security": {"min_tasks": 5, "target_tasks": 12, "bonus_tasks": 20,
        "min_success_rate": 0.85, "target_success_rate": 0.90, "bonus_success_rate": 0.95,
        "max_avg_time": 45, "max_hallucinations": 0,
        "rewards": {"meet_target": 30, "exceed_target": 60, "perfect": 120,
                    "miss_min": -25, "hallucination": -40}},
    "reviewer": {"min_tasks": 8, "target_tasks": 15, "bonus_tasks": 22,
        "min_success_rate": 0.75, "target_success_rate": 0.85, "bonus_success_rate": 0.92,
        "max_avg_time": 35, "max_hallucinations": 1,
        "rewards": {"meet_target": 20, "exceed_target": 45, "perfect": 90,
                    "miss_min": -20, "hallucination": -30}},
}

DEFAULT_TARGET = {
    "min_tasks": 5, "target_tasks": 10, "bonus_tasks": 15,
    "min_success_rate": 0.70, "target_success_rate": 0.80, "bonus_success_rate": 0.90,
    "max_avg_time": 45, "max_hallucinations": 2,
    "rewards": {"meet_target": 15, "exceed_target": 35, "perfect": 70,
                "miss_min": -15, "hallucination": -25},
}


class DailyTargetSystem:
    def __init__(self, file_path: str = "data/company/daily_targets.json"):
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        self.file_path = file_path
        self.data = self._load()

    def _load(self):
        if Path(self.file_path).exists():
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"days": {}, "history": []}

    def _save(self):
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def _today(self):
        return datetime.now().strftime("%Y-%m-%d")

    def get_target_for(self, specialty):
        return DAILY_TARGETS.get(specialty, DEFAULT_TARGET)

    def record_task(self, soldier_id, specialty, success, duration, hallucination=False):
        today = self._today()
        self.data["days"].setdefault(today, {})
        entry = self.data["days"][today].setdefault(soldier_id, {
            "specialty": specialty, "tasks": 0, "success": 0, "failed": 0,
            "hallucinations": 0, "total_time": 0.0, "started_at": time.time(),
        })
        entry["tasks"] += 1
        if success: entry["success"] += 1
        else: entry["failed"] += 1
        if hallucination: entry["hallucinations"] += 1
        entry["total_time"] += duration
        self._save()

    def evaluate_soldier(self, soldier_id, specialty):
        today = self._today()
        entry = self.data["days"].get(today, {}).get(soldier_id)
        if not entry:
            return {"status": "no_activity", "soldier_id": soldier_id}
        target = self.get_target_for(specialty)
        tasks = entry["tasks"]
        rate = entry["success"] / max(tasks, 1)
        avg = entry["total_time"] / max(tasks, 1)
        hallucinations = entry["hallucinations"]

        verdict = "UNKNOWN"
        coins = 0
        details = []
        if tasks < target["min_tasks"]:
            verdict = "MISS_MIN"; coins = target["rewards"]["miss_min"]
            details.append(f"Tasks {tasks} < min {target['min_tasks']}")
        elif tasks >= target["bonus_tasks"] and rate >= target["bonus_success_rate"]:
            verdict = "PERFECT"; coins = target["rewards"]["perfect"]
            details.append(f"Elite: {tasks} @ {rate:.0%}")
        elif tasks >= target["target_tasks"] and rate >= target["target_success_rate"]:
            verdict = "EXCEED"; coins = target["rewards"]["exceed_target"]
            details.append(f"Exceeded: {tasks} @ {rate:.0%}")
        elif tasks >= target["target_tasks"]:
            verdict = "MEET"; coins = target["rewards"]["meet_target"]
            details.append(f"Met: {tasks}")
        else:
            verdict = "PARTIAL"
            details.append(f"Partial: {tasks}/{target['target_tasks']}")

        if hallucinations > target["max_hallucinations"]:
            extra = hallucinations - target["max_hallucinations"]
            coins += target["rewards"]["hallucination"] * extra
            details.append(f"Hallucinations: {hallucinations}")
        if avg < target["max_avg_time"]:
            coins += 5
            details.append(f"Fast: {avg:.1f}s")

        return {"soldier_id": soldier_id, "specialty": specialty, "date": today,
                "tasks": tasks, "success_rate": round(rate, 3), "avg_time": round(avg, 2),
                "hallucinations": hallucinations, "target": target,
                "verdict": verdict, "coins_delta": coins, "details": details}

    def evaluate_all(self, soldiers):
        results = []
        for s in soldiers:
            r = self.evaluate_soldier(s.id, s.specialty)
            if r.get("status") != "no_activity":
                results.append(r)
        verdicts = {}
        total = 0
        for r in results:
            v = r["verdict"]; verdicts[v] = verdicts.get(v, 0) + 1
            total += r["coins_delta"]
        self.data["history"].append({"date": self._today(),
            "evaluations": len(results), "verdicts": verdicts,
            "total_coins": total, "time": time.time()})
        self._save()
        return {"date": self._today(), "total_evaluated": len(results),
                "verdicts": verdicts, "total_coins_delta": total, "details": results}

    def get_leaderboard(self):
        today = self._today()
        entries = self.data["days"].get(today, {})
        board = []
        for sid, entry in entries.items():
            rate = entry["success"] / max(entry["tasks"], 1)
            score = entry["success"] * rate * 100
            board.append({"soldier_id": sid, "specialty": entry["specialty"],
                "tasks": entry["tasks"], "success_rate": round(rate, 3),
                "score": round(score, 1)})
        board.sort(key=lambda x: x["score"], reverse=True)
        return board

    def stats(self):
        today = self._today()
        return {"today": today,
                "active_soldiers": len(self.data["days"].get(today, {})),
                "days_tracked": len(self.data["days"]),
                "history_events": len(self.data["history"])}
