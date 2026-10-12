"""Extracted from novamind.py — section: cost
Original lines: 3419-3569
Class: CostTracker
"""
# ═══════════════════════════════════════════════════════
#  AUTO-EXTRACTED — do not edit by hand unless verified
# ═══════════════════════════════════════════════════════

# ═══ SECTION: COMPANY — Cost Tracker ═══
# Source: core/company/cost_tracker.py

"""Cost Tracker - يتتبع التوكن والتكلفة لكل جندي."""
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger("CostTracker")

# تكلفة تقديرية لكل 1000 token (بالدولار)
PROVIDER_COSTS = {
    "ollama":     0.0,        # محلي = مجاني
    "ollama-qwen-local": 0.0,
    "glm-4.7-flash": 0.0,     # مجاني (خلال الحصة)
    "glm-account-1": 0.0,
    "glm-account-2": 0.0,
    "glm-account-3": 0.0,
    "glm-account-4": 0.0,
    "glm-account-5": 0.0,
    "gemini":     0.001,
    "openai":     0.005,
}


class CostTracker:
    """يتتبع الاستهلاك: tokens + تكلفة + حصص."""
    
    def __init__(self, file_path: str = "data/company/costs.json"):
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        self.file_path = file_path
        self.data = {
            "soldiers": {},       # soldier_id -> {tokens, cost, calls}
            "providers": {},      # provider -> {tokens, cost, calls}
            "specialties": {},    # specialty -> {tokens, cost, calls}
            "daily": {},          # YYYY-MM-DD -> {tokens, cost}
            "totals": {"tokens": 0, "cost": 0.0, "calls": 0},
        }
        self._load()
    
    def _load(self):
        if Path(self.file_path).exists():
            with open(self.file_path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
    
    def _save(self):
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    
    def _today(self) -> str:
        return time.strftime("%Y-%m-%d")
    
    def _estimate_tokens(self, text: str) -> int:
        """تقدير بسيط: 4 أحرف ≈ 1 token."""
        return max(1, len(text) // 4)
    
    def record(
        self,
        soldier_id: str,
        specialty: str,
        provider: str,
        prompt: str,
        response: str,
    ) -> Dict[str, Any]:
        """يسجّل استدعاءً."""
        tokens_in = self._estimate_tokens(prompt)
        tokens_out = self._estimate_tokens(response)
        total_tokens = tokens_in + tokens_out
        
        cost_per_k = PROVIDER_COSTS.get(provider, 0.0)
        cost = (total_tokens / 1000.0) * cost_per_k
        
        # سجّل للجندي
        if soldier_id not in self.data["soldiers"]:
            self.data["soldiers"][soldier_id] = {"tokens": 0, "cost": 0.0, "calls": 0}
        self.data["soldiers"][soldier_id]["tokens"] += total_tokens
        self.data["soldiers"][soldier_id]["cost"] += cost
        self.data["soldiers"][soldier_id]["calls"] += 1
        
        # سجّل للمزود
        if provider not in self.data["providers"]:
            self.data["providers"][provider] = {"tokens": 0, "cost": 0.0, "calls": 0}
        self.data["providers"][provider]["tokens"] += total_tokens
        self.data["providers"][provider]["cost"] += cost
        self.data["providers"][provider]["calls"] += 1
        
        # سجّل للتخصص
        if specialty not in self.data["specialties"]:
            self.data["specialties"][specialty] = {"tokens": 0, "cost": 0.0, "calls": 0}
        self.data["specialties"][specialty]["tokens"] += total_tokens
        self.data["specialties"][specialty]["cost"] += cost
        self.data["specialties"][specialty]["calls"] += 1
        
        # سجّل لليوم
        today = self._today()
        if today not in self.data["daily"]:
            self.data["daily"][today] = {"tokens": 0, "cost": 0.0}
        self.data["daily"][today]["tokens"] += total_tokens
        self.data["daily"][today]["cost"] += cost
        
        # الإجماليات
        self.data["totals"]["tokens"] += total_tokens
        self.data["totals"]["cost"] += cost
        self.data["totals"]["calls"] += 1
        
        self._save()
        
        return {
            "soldier_id": soldier_id,
            "tokens": total_tokens,
            "cost": round(cost, 6),
            "provider": provider,
        }
    
    def get_soldier_cost(self, soldier_id: str) -> Dict[str, Any]:
        return self.data["soldiers"].get(soldier_id, {"tokens": 0, "cost": 0.0, "calls": 0})
    
    def get_provider_cost(self, provider: str) -> Dict[str, Any]:
        return self.data["providers"].get(provider, {"tokens": 0, "cost": 0.0, "calls": 0})
    
    def today_cost(self) -> Dict[str, Any]:
        return self.data["daily"].get(self._today(), {"tokens": 0, "cost": 0.0})
    
    def top_consumers(self, n: int = 5) -> List[Dict]:
        """أكثر الجنود استهلاكاً."""
        soldiers = [
            {"soldier_id": k, **v}
            for k, v in self.data["soldiers"].items()
        ]
        soldiers.sort(key=lambda x: x["tokens"], reverse=True)
        return soldiers[:n]
    
    def stats(self) -> Dict[str, Any]:
        return {
            "totals": self.data["totals"],
            "today": self.today_cost(),
            "providers": self.data["providers"],
            "top_soldiers": self.top_consumers(3),
            "specialties": self.data["specialties"],
        }
    
    def reset(self):
        """يحذف كل الإحصائيات (اختبار)."""
        self.data = {
            "soldiers": {}, "providers": {}, "specialties": {},
            "daily": {}, "totals": {"tokens": 0, "cost": 0.0, "calls": 0},
        }
        self._save()

