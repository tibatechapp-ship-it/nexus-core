"""
CostAwareRouter - Smart routing based on task, cost, and availability
- Tracks remaining budget per provider
- Chooses cheapest provider that meets quality needs
- Auto-failover when quota exhausted
- Daily cost reports
"""
import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
import os

BASE = Path(os.environ.get("NOVAMIND_HOME", str(Path(__file__).resolve().parent.parent)))
COST_FILE = BASE / "memory" / "cost_tracking.json"

logger = logging.getLogger("cost_router")


# ═══════════════════════════════════════════════════════
#  Provider cost profiles (per 1M tokens)
# ═══════════════════════════════════════════════════════
PROVIDER_COSTS = {
    "local": {
        "input": 0.0,       # free (uses your CPU)
        "output": 0.0,
        "quality": 6,       # 1-10 scale
        "speed": 9,
        "free_quota": None,
    },
    "gemini": {
        "input": 0.075,
        "output": 0.30,
        "quality": 9,
        "speed": 7,
        "free_quota": {"daily": 1_000_000, "rpm": 15},
    },
    "qwen": {
        "input": 0.0,       # free tier: 70M tokens
        "output": 0.0,
        "quality": 8,
        "speed": 8,
        "free_quota": {"total": 70_000_000},
    },
    "deepseek": {
        "input": 0.14,
        "output": 0.28,
        "quality": 8,
        "speed": 8,
        "free_quota": None,
    },
    "openai": {
        "input": 0.15,
        "output": 0.60,
        "quality": 9,
        "speed": 7,
        "free_quota": None,
    },
}


# ═══════════════════════════════════════════════════════
#  Task quality requirements
# ═══════════════════════════════════════════════════════
TASK_QUALITY = {
    "code":       6,   # simple tasks - any provider
    "quick":      4,   # very simple - local preferred
    "analysis":   8,   # needs reasoning
    "learn":      8,   # needs understanding
    "plan":       8,   # needs strategy
    "architect":  9,   # needs deep thinking
}


# ═══════════════════════════════════════════════════════
#  Cost Tracking
# ═══════════════════════════════════════════════════════
class CostTracker:
    def __init__(self, path: Path = COST_FILE):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self):
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                # Reset daily quota if new day
                last = data.get("last_reset", "")
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                if last != today:
                    data["daily"] = {}
                    data["last_reset"] = today
                return data
            except Exception:
                pass
        return {
            "lifetime": {},   # provider -> {input_tokens, output_tokens, cost, calls, failures}
            "daily": {},      # provider -> {input_tokens, output_tokens, cost, calls}
            "last_reset": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }

    def _save(self):
        try:
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.warning("failed to save cost tracking: " + str(e))

    def record_call(self, provider: str, input_tokens: int,
                    output_tokens: int, success: bool):
        """Records one API call."""
        cost_profile = PROVIDER_COSTS.get(provider, {})
        in_cost = cost_profile.get("input", 0.0)
        out_cost = cost_profile.get("output", 0.0)

        cost = (input_tokens / 1_000_000) * in_cost + \
               (output_tokens / 1_000_000) * out_cost

        for scope in ("lifetime", "daily"):
            if provider not in self.data[scope]:
                self.data[scope][provider] = {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost": 0.0,
                    "calls": 0,
                    "failures": 0,
                }
            entry = self.data[scope][provider]
            entry["input_tokens"] += input_tokens
            entry["output_tokens"] += output_tokens
            entry["cost"] += cost
            entry["calls"] += 1
            if not success:
                entry["failures"] += 1

        self._save()

    def daily_tokens(self, provider: str) -> int:
        """Returns total tokens used today by provider."""
        entry = self.data["daily"].get(provider, {})
        return entry.get("input_tokens", 0) + entry.get("output_tokens", 0)

    def lifetime_cost(self, provider: str) -> float:
        return self.data["lifetime"].get(provider, {}).get("cost", 0.0)

    def is_quota_exceeded(self, provider: str) -> bool:
        """Checks if provider quota is exceeded today."""
        cost_profile = PROVIDER_COSTS.get(provider, {})
        quota = cost_profile.get("free_quota")
        if not quota:
            return False
        if "daily" in quota:
            return self.daily_tokens(provider) >= quota["daily"]
        if "total" in quota:
            lifetime = self.data["lifetime"].get(provider, {})
            total = lifetime.get("input_tokens", 0) + lifetime.get("output_tokens", 0)
            return total >= quota["total"]
        return False

    def summary(self) -> Dict:
        """Returns cost summary."""
        total_lifetime = sum(
            v.get("cost", 0.0) for v in self.data["lifetime"].values()
        )
        total_daily = sum(
            v.get("cost", 0.0) for v in self.data["daily"].values()
        )
        return {
            "total_lifetime_cost_usd": round(total_lifetime, 4),
            "total_daily_cost_usd": round(total_daily, 4),
            "lifetime": self.data["lifetime"],
            "daily": self.data["daily"],
        }


# ═══════════════════════════════════════════════════════
#  Smart Router
# ═══════════════════════════════════════════════════════
class CostAwareRouter:
    def __init__(self, base_router):
        self.base_router = base_router
        self.tracker = CostTracker()

    def _score_provider(self, provider: str, task_type: str,
                        need_speed: bool = False) -> float:
        """
        Higher score = better choice.
        Factors: quality match, cost, speed, availability.
        """
        profile = PROVIDER_COSTS.get(provider, {})
        if not profile:
            return -1

        quality = profile.get("quality", 5)
        speed = profile.get("speed", 5)
        in_cost = profile.get("input", 0.1)
        out_cost = profile.get("output", 0.3)

        # Quality match
        needed = TASK_QUALITY.get(task_type, 6)
        if quality < needed:
            return -10  # don't use if quality insufficient

        # Cost penalty (lower is better)
        avg_cost = (in_cost + out_cost) / 2
        cost_penalty = avg_cost * 3

        # Speed bonus
        speed_bonus = speed * 0.5

        # Availability check
        if self.tracker.is_quota_exceeded(provider):
            return -10

        score = quality * 1.0 + speed_bonus - cost_penalty
        return score

    def choose(self, task_type: str) -> List[str]:
        """Returns ranked list of preferred providers."""
        # Get all available providers from base router
        available = [p["name"] for p in self.base_router.list_providers()]

        # Score each
        scored = []
        for provider in available:
            score = self._score_provider(provider, task_type)
            if score > 0:
                scored.append((provider, score))

        # Sort by score desc
        scored.sort(key=lambda x: -x[1])

        # If none pass, fall back to all available
        if not scored:
            return available

        return [p for p, _ in scored]

    def generate_for_task(self, task_type: str, prompt: str,
                          system: str = "", temperature: float = 0.2,
                          max_tokens: Optional[int] = None) -> Dict:
        """
        Cost-aware generation.
        Tries best provider first, falls back in order.
        """
        candidates = self.choose(task_type)

        if not candidates:
            return {
                "ok": False, "text": "", "provider": "", "model": "",
                "error": "no available providers", "elapsed": 0.0,
            }

        last_error = ""
        for provider in candidates:
            # Estimate tokens (rough: 4 chars/token)
            in_tokens = (len(prompt) + len(system)) // 4
            out_tokens = max_tokens or 500

            result = self.base_router.generate(
                prompt=prompt,
                system=system,
                role="fast" if TASK_QUALITY.get(task_type, 6) <= 6 else "smart",
                temperature=temperature,
                max_tokens=max_tokens,
                provider=provider,
                allow_fallback=False,
            )

            success = result.get("ok", False)
            self.tracker.record_call(
                provider, in_tokens, out_tokens if success else 0, success
            )

            if success:
                logger.info("cost_router chose: " + provider +
                            " for task: " + task_type)
                return result

            last_error = result.get("error", "")

        return {
            "ok": False, "text": "", "provider": "", "model": "",
            "error": last_error or "all providers failed", "elapsed": 0.0,
        }

    def stats(self) -> Dict:
        return {
            "cost_tracker": self.tracker.summary(),
            "provider_profiles": PROVIDER_COSTS,
            "task_requirements": TASK_QUALITY,
        }


# Singleton factory
_cost_router = None

def get_cost_router():
    global _cost_router
    if _cost_router is None:
        from novamind.core.llm_router import get_router
        _cost_router = CostAwareRouter(get_router())
    return _cost_router
