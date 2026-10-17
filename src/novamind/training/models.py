"""Value model for the agent-training pipeline (P3).

Pure values only — no I/O, no clock, no randomness — so a run can be reasoned
about and asserted on without touching the network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Tuple

#: Score an agent must reach to earn a certificate.  Mirrors
#: ``TrainingPlan.graduation_min_score`` and is re-checked here as a hard gate,
#: so a plan can never quietly lower the bar.
GRADUATION_MIN_SCORE: float = 0.75

#: Below this a run is a hard failure rather than "needs retraining".
RETRAIN_FLOOR: float = 0.50


class TrainingVerdict(str, Enum):
    """Outcome of one full training run."""

    GRADUATED = "graduated"
    NEEDS_RETRAINING = "needs_retraining"
    FAILED = "failed"


@dataclass(frozen=True)
class TrainingRun:
    """The immutable record of one completed training run."""

    run_id: str
    agent_id: str
    spec: str
    started_at: float
    finished_at: float
    completion_rate: float
    training_score: float
    gate_score: float
    final_score: float
    verdict: str
    certified: bool
    phases: Tuple[Dict[str, Any], ...] = ()
    detail: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        """Wall-clock length of the run, in seconds."""
        return round(float(self.finished_at) - float(self.started_at), 6)

    def to_dict(self) -> Dict[str, Any]:
        """A JSON-friendly view (tuples become lists via ``json``)."""
        return {
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "spec": self.spec,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": self.duration,
            "completion_rate": self.completion_rate,
            "training_score": self.training_score,
            "gate_score": self.gate_score,
            "final_score": self.final_score,
            "verdict": self.verdict,
            "certified": self.certified,
            "phases": [dict(p) for p in self.phases],
            "detail": dict(self.detail),
        }


def verdict_for(
    graduated: bool, final_score: float, *,
    completion_rate: float = 1.0, critical: bool = False,
) -> str:
    """Map a finished run onto a :class:`TrainingVerdict` value.

    Only a genuinely graduated run is ``graduated``.  Everything else is judged
    on *why* it fell short: a critical module failure or a curriculum that was
    mostly not completed is a hard ``failed``, while a run that completed the
    work at an insufficient level is ``needs_retraining``.
    """
    if graduated:
        return TrainingVerdict.GRADUATED.value
    if critical or float(completion_rate) < 0.5:
        return TrainingVerdict.FAILED.value
    if float(final_score) >= RETRAIN_FLOOR:
        return TrainingVerdict.NEEDS_RETRAINING.value
    return TrainingVerdict.FAILED.value
