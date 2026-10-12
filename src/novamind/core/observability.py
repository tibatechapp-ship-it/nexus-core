"""
Observability — Metrics and telemetry for NovaMind.

Tracks:
- LLM calls (provider, model, latency, success/failure)
- Agent executions (name, duration, result)
- Errors

Usage:
    from novamind.core.observability import metrics
    metrics.track_llm_call("gemini", "gemini-2.0", 1.5, True)
    print(metrics.snapshot())
"""
import time
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List
from datetime import datetime, timezone

logger = logging.getLogger("core.observability")


@dataclass
class LLMCallMetric:
    provider: str
    model: str
    latency: float
    success: bool
    timestamp: str


@dataclass
class AgentCallMetric:
    agent: str
    duration: float
    success: bool
    timestamp: str


class MetricsTracker:
    """In-memory metrics tracker."""

    def __init__(self, max_samples: int = 10000):
        self.max_samples = max_samples
        self.start_time = time.time()
        self.llm_calls: List[LLMCallMetric] = []
        self.llm_by_provider: Dict[str, int] = defaultdict(int)
        self.llm_failures: Dict[str, int] = defaultdict(int)
        self.agent_calls: List[AgentCallMetric] = []
        self.agent_by_name: Dict[str, int] = defaultdict(int)
        self.agent_failures: Dict[str, int] = defaultdict(int)
        self.errors: int = 0

    def track_llm_call(self, provider: str, model: str,
                       latency: float, success: bool) -> None:
        self.llm_calls.append(LLMCallMetric(
            provider=provider, model=model, latency=latency,
            success=success,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))
        self.llm_by_provider[provider] += 1
        if not success:
            self.llm_failures[provider] += 1
            self.errors += 1
        if len(self.llm_calls) > self.max_samples:
            self.llm_calls = self.llm_calls[-self.max_samples:]

    def track_agent_call(self, agent: str, duration: float,
                         success: bool) -> None:
        self.agent_calls.append(AgentCallMetric(
            agent=agent, duration=duration, success=success,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))
        self.agent_by_name[agent] += 1
        if not success:
            self.agent_failures[agent] += 1
            self.errors += 1
        if len(self.agent_calls) > self.max_samples:
            self.agent_calls = self.agent_calls[-self.max_samples:]

    def track_error(self, error_type: str = "generic") -> None:
        self.errors += 1
        logger.debug(f"error tracked: {error_type}")

    def snapshot(self) -> Dict:
        total_llm = len(self.llm_calls)
        total_agent = len(self.agent_calls)
        llm_successes = sum(1 for m in self.llm_calls if m.success)
        agent_successes = sum(1 for m in self.agent_calls if m.success)

        return {
            "total_llm_calls": total_llm,
            "total_agent_calls": total_agent,
            "llm_success_rate": round(
                (llm_successes / total_llm) if total_llm else 0.0, 4
            ),
            "agent_success_rate": round(
                (agent_successes / total_agent) if total_agent else 0.0, 4
            ),
            "avg_llm_latency": round(
                (sum(m.latency for m in self.llm_calls) / total_llm)
                if total_llm else 0.0, 4
            ),
            "avg_agent_duration": round(
                (sum(m.duration for m in self.agent_calls) / total_agent)
                if total_agent else 0.0, 4
            ),
            "llm_by_provider": dict(self.llm_by_provider),
            "llm_failures": dict(self.llm_failures),
            "agent_by_name": dict(self.agent_by_name),
            "agent_failures": dict(self.agent_failures),
            "errors": self.errors,
            "uptime_seconds": round(time.time() - self.start_time, 2),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def reset(self) -> None:
        self.__init__(max_samples=self.max_samples)

    def prometheus_format(self) -> str:
        lines = [
            "# HELP novamind_llm_calls_total Total LLM calls",
            "# TYPE novamind_llm_calls_total counter",
            f"novamind_llm_calls_total {len(self.llm_calls)}",
            "",
            "# HELP novamind_agent_calls_total Total agent calls",
            "# TYPE novamind_agent_calls_total counter",
            f"novamind_agent_calls_total {len(self.agent_calls)}",
            "",
            "# HELP novamind_errors_total Total errors",
            "# TYPE novamind_errors_total counter",
            f"novamind_errors_total {self.errors}",
        ]
        for provider, count in self.llm_by_provider.items():
            lines.append(
                f'novamind_llm_by_provider{{provider="{provider}"}} {count}'
            )
        for agent, count in self.agent_by_name.items():
            lines.append(
                f'novamind_agent_calls{{agent="{agent}"}} {count}'
            )
        return "\n".join(lines)


# Singleton
metrics = MetricsTracker()


__all__ = ["MetricsTracker", "metrics", "LLMCallMetric", "AgentCallMetric"]
