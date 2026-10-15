"""Pure scoring for the Agent Genome (v2.2) — no I/O, no dependencies.

A genome's **standing** (0-1) is a weighted blend of how often the agent
succeeded, how well it aligned with council verdicts (consensus), and how fast
it replied.  Everything here is a plain function so the phone framework gate can
unit-test the whole model without a database or a network.
"""

from __future__ import annotations

__all__ = [
    "NEUTRAL_STANDING",
    "PROMOTE_AT",
    "PROBATION_BELOW",
    "success_rate",
    "avg_latency",
    "consensus_avg",
    "speed_score",
    "compute_standing",
    "classify",
]

# ── tunables ─────────────────────────────────────────────────────────────────
NEUTRAL_STANDING = 0.5      # a brand-new agent starts in the middle
PROMOTE_AT = 0.7            # standing at/above this → promoted
PROBATION_BELOW = 0.4       # standing below this → probation (re-training)
SLOW_MS = 30_000.0          # a reply this slow (or slower) scores 0 on speed

_W_SUCCESS = 0.6            # success-rate weight
_W_CONSENSUS = 0.3          # verdict-alignment weight
_W_SPEED = 0.1              # speed weight


def success_rate(successes: int, runs: int) -> float:
    """Fraction of runs that succeeded, in [0, 1] (0.0 when never run)."""
    if runs <= 0:
        return 0.0
    return max(0.0, min(1.0, successes / runs))


def avg_latency(latency_sum_ms: int, runs: int) -> float:
    """Mean reply latency in milliseconds (0.0 when never run)."""
    if runs <= 0:
        return 0.0
    return max(0.0, latency_sum_ms / runs)


def consensus_avg(consensus_sum: float, consensus_n: int) -> float:
    """Mean consensus alignment, in [0, 1]. Neutral (0.5) with no samples."""
    if consensus_n <= 0:
        return 0.5
    return max(0.0, min(1.0, consensus_sum / consensus_n))


def speed_score(avg_latency_ms: float) -> float:
    """Map a mean latency to a [0, 1] speed score (faster → closer to 1)."""
    if avg_latency_ms <= 0:
        return 1.0
    return max(0.0, min(1.0, 1.0 - (avg_latency_ms / SLOW_MS)))


def compute_standing(runs: int, successes: int, consensus_sum: float,
                     consensus_n: int, latency_sum_ms: int,
                     prior: float = NEUTRAL_STANDING) -> float:
    """Weighted standing (0-1); an agent that never ran keeps its prior."""
    if runs <= 0:
        return round(float(prior), 4)
    score = (
        _W_SUCCESS * success_rate(successes, runs)
        + _W_CONSENSUS * consensus_avg(consensus_sum, consensus_n)
        + _W_SPEED * speed_score(avg_latency(latency_sum_ms, runs))
    )
    return round(max(0.0, min(1.0, score)), 4)


def classify(standing: float) -> str:
    """Lifecycle bucket for a standing value."""
    if standing >= PROMOTE_AT:
        return "promoted"
    if standing < PROBATION_BELOW:
        return "probation"
    return "active"
