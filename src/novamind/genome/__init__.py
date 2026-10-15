"""Agent Genome (v2.2) — agents that evolve from real outcomes."""

from __future__ import annotations

from .genome import DEFAULT_NAMES, DEFAULT_PERSONAS, Genome
from .scoring import (
    NEUTRAL_STANDING,
    PROBATION_BELOW,
    PROMOTE_AT,
    classify,
    compute_standing,
)

__all__ = [
    "Genome",
    "DEFAULT_PERSONAS",
    "DEFAULT_NAMES",
    "compute_standing",
    "classify",
    "NEUTRAL_STANDING",
    "PROMOTE_AT",
    "PROBATION_BELOW",
]
