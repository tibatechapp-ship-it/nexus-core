"""Monitoring — تتبع استدعاءات LLM، التكلفة، التوكن، الوقت."""
from __future__ import annotations
import os
import sys
import json
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional

# ═══ أسعار تقديرية (لكل 1M توكن) ═══
PRICE_PER_1M = {
    "groq": {"input": 0.05, "output": 0.08},
    "gemini": {"input": 0.075, "output": 0.30},
    "openrouter": {"input": 0.10, "output": 0.20},
    "mistral": {"input": 0.25, "output": 0.25},
    "default": {"input": 0.10, "output": 0.20},
}


@dataclass
class LLMCall:
    """استدعاء واحد لـ LLM."""
    timestamp: float
    provider: str
    model: str
    elapsed: float
    ok: bool
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    error: str = ""
    task_type: str = ""
    caller: str = ""  # council/agent/loop


class Monitor:
    """مراقب الإحصائيات."""

    def __init__(self, log_dir: str = None):
        self.log_dir = log_dir or os.path.expanduser("~/.nexus/data/metrics")
        os.makedirs(self.log_dir, exist_ok=True)
        self._today_file = self._path_for_today()
        self._session_calls: list[LLMCall] = []

    def _path_for_today(self) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.log_dir, f"calls_{today}.jsonl")

    def _estimate_tokens(self, text: str) -> int:
        """تقدير تقريبي: كل 4 أحرف ≈ توكن."""
        if not text:
            return 0
        # تقدير مختلط عربي/إنجليزي
        return max(1, len(text) // 4)

    def _estimate_cost(self, provider: str, tokens_in: int, tokens_out: int) -> float:
        """تقدير التكلفة بالدولار."""
        key = "default"
        p_lower = provider.lower()
        for k in PRICE_PER_1M:
            if k in p_lower:
                key = k
                break

        rates = PRICE_PER_1M[key]
        cost = (tokens_in / 1_000_000) * rates["input"] + \
               (tokens_out / 1_000_000) * rates["output"]
        return round(cost, 6)

    def log_call(
        self,
        provider: str,
        model: str,
        elapsed: float,
        ok: bool,
        prompt: str = "",
        response: str = "",
        error: str = "",
        task_type: str = "",
        caller: str = "",
    ) -> LLMCall:
        """يسجّل استدعاء."""
        tokens_in = self._estimate_tokens(prompt)
        tokens_out = self._estimate_tokens(response)
        cost = self._estimate_cost(provider, tokens_in, tokens_out)

        call = LLMCall(
            timestamp=time.time(),
            provider=provider,
            model=model,
            elapsed=round(elapsed, 3),
            ok=ok,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            error=error[:200],
            task_type=task_type,
            caller=caller,
        )

        # احفظ في الملف
        try:
            with open(self._today_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(call), ensure_ascii=False) + "\n")
        except Exception:
            pass

        # احفظ في الذاكرة
        self._session_calls.append(call)
        return call

    def get_today_stats(self) -> dict:
        """إحصائيات اليوم."""
        if not os.path.exists(self._today_file):
            return self._empty_stats()

        calls = []
        try:
            with open(self._today_file, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        calls.append(json.loads(line))
        except Exception:
            pass

        return self._compute_stats(calls)

    def get_session_stats(self) -> dict:
        """إحصائيات الجلسة الحالية."""
        return self._compute_stats([asdict(c) for c in self._session_calls])

    def _compute_stats(self, calls: list) -> dict:
        if not calls:
            return self._empty_stats()

        total_time = sum(c.get("elapsed", 0) for c in calls)
        total_tokens_in = sum(c.get("tokens_in", 0) for c in calls)
        total_tokens_out = sum(c.get("tokens_out", 0) for c in calls)
        total_cost = sum(c.get("cost_usd", 0) for c in calls)
        successes = sum(1 for c in calls if c.get("ok"))
        failures = len(calls) - successes

        # تجميع حسب المزود
        by_provider = {}
        for c in calls:
            p = c.get("provider", "unknown")
            if p not in by_provider:
                by_provider[p] = {"calls": 0, "time": 0, "tokens": 0, "cost": 0}
            by_provider[p]["calls"] += 1
            by_provider[p]["time"] += c.get("elapsed", 0)
            by_provider[p]["tokens"] += c.get("tokens_in", 0) + c.get("tokens_out", 0)
            by_provider[p]["cost"] += c.get("cost_usd", 0)

        return {
            "total_calls": len(calls),
            "successes": successes,
            "failures": failures,
            "success_rate": round(successes / len(calls) * 100, 1),
            "total_time_s": round(total_time, 2),
            "avg_time_s": round(total_time / len(calls), 3),
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "total_tokens": total_tokens_in + total_tokens_out,
            "total_cost_usd": round(total_cost, 6),
            "by_provider": by_provider,
        }

    def _empty_stats(self) -> dict:
        return {
            "total_calls": 0,
            "successes": 0,
            "failures": 0,
            "success_rate": 0.0,
            "total_time_s": 0.0,
            "avg_time_s": 0.0,
            "total_tokens_in": 0,
            "total_tokens_out": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "by_provider": {},
        }

    def clear_today(self) -> int:
        """يحذف سجل اليوم."""
        if os.path.exists(self._today_file):
            count = sum(1 for _ in open(self._today_file))
            os.remove(self._today_file)
            return count
        return 0


# Singleton
_monitor = None

def get_monitor() -> Monitor:
    global _monitor
    if _monitor is None:
        _monitor = Monitor()
    return _monitor
