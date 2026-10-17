"""Agent Genome v2 (v1.14.0) — judgement-accuracy evolution.

The v1 genome (``novamind.genome``) scored an agent on *how often it succeeded*
plus its alignment with a verdict it never saw while debating.  v2 scores the one
thing a council member actually exists for: **was its judgement right?**  Every
observation compares the member's own explicit stance with the council's final
verdict — agreement builds fitness, dissent erodes it, and recency outweighs
history.

Three ideas separate v2 from v1:

* **Confidence shrinkage** — one lucky agreement must not make a one-run member
  look elite.  ``confidence = n / (n + CONFIDENCE_K)`` keeps fitness near
  ``NEUTRAL_FITNESS`` until the evidence accumulates.
* **Recency (EWMA)** — fitness follows an exponentially weighted moving average
  of agreement, so an agent that improved today outranks one that was good last
  month.
* **Per-stance traits** — accuracy is tracked per final verdict
  (``approve`` / ``reject`` / ``human_review``), so the system can report *what*
  an agent is good at, not merely *how* good it is.

Pure and hermetic: standard library only, no I/O, no clock, no randomness, no
database.  Persistence is ``to_dict`` / ``from_dict`` (JSON-ready), which keeps
the phone gate and CI able to exercise the whole model offline.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

__all__ = [
    "CONFIDENCE_K",
    "DEFAULT_ALPHA",
    "ELITE_AT",
    "FINAL_VERDICTS",
    "HISTORY_LIMIT",
    "MIN_OBSERVATIONS",
    "NEUTRAL_FITNESS",
    "PROBATION_BELOW",
    "STANCE_TO_FINAL",
    "GenomeV2",
    "agreement",
    "classify_fitness",
    "confidence",
    "empty_genome",
    "ewma_update",
    "fitness",
    "get_genome_v2",
    "reset_genome_v2",
    "stance_of",
    "trait_accuracy",
]

# ── tunables ─────────────────────────────────────────────────────────────────
NEUTRAL_FITNESS = 0.5       # a brand-new agent sits in the middle
ELITE_AT = 0.75             # fitness at/above this → elite
PROBATION_BELOW = 0.35      # fitness below this → probationary (re-train)
CONFIDENCE_K = 5.0          # observations needed before evidence is trusted
DEFAULT_ALPHA = 0.35        # EWMA weight of the newest sample
MIN_OBSERVATIONS = 5        # below this an agent is still "under observation"
HISTORY_LIMIT = 50          # bounded per-agent event trail

#: The verdicts a council can settle on.
FINAL_VERDICTS: tuple[str, ...] = ("approve", "reject", "human_review")

#: How a member's explicit stance maps onto a final verdict.
STANCE_TO_FINAL: Dict[str, str] = {
    "yes": "approve",
    "no": "reject",
    "mid": "human_review",
}


# ── pure helpers (no state, fully unit-testable) ─────────────────────────────
def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Clamp ``value`` into ``[low, high]``."""
    return max(low, min(high, float(value)))


def stance_of(verdict: Any) -> Optional[str]:
    """Normalise a member stance *or* a final verdict to a final verdict.

    ``"yes"``/``"approve"`` → ``"approve"``; ``"no"``/``"reject"`` → ``"reject"``;
    ``"mid"``/``"human_review"`` → ``"human_review"``.  Anything unrecognised
    (including ``None`` and ``""``) → ``None``.
    """
    key = str(verdict or "").strip().lower()
    if key in STANCE_TO_FINAL:
        return STANCE_TO_FINAL[key]
    if key in FINAL_VERDICTS:
        return key
    return None


def agreement(member_verdict: Any, final_verdict: Any) -> Optional[bool]:
    """Did this member's stance match the council's final verdict?

    Returns ``None`` when either side is unrecognised — an unscorable
    observation that must not be counted as agreement *or* dissent.
    """
    member = stance_of(member_verdict)
    final = stance_of(final_verdict)
    if member is None or final is None:
        return None
    return member == final


def confidence(observations: int, k: float = CONFIDENCE_K) -> float:
    """How much the evidence is worth, in [0, 1] — ``n / (n + k)``."""
    n = max(0, int(observations))
    if n <= 0:
        return 0.0
    weight = max(0.0, float(k))
    if weight == 0.0:
        return 1.0
    return round(n / (n + weight), 6)


def ewma_update(previous: float, sample: float, alpha: float = DEFAULT_ALPHA) -> float:
    """Blend one ``sample`` into the running average (recency-weighted)."""
    a = _clamp(alpha)
    return round(_clamp((1.0 - a) * float(previous) + a * float(sample)), 6)


def fitness(observations: int, ewma: float, *,
            prior: float = NEUTRAL_FITNESS) -> float:
    """Confidence-shrunk fitness in [0, 1].

    With no observations the result is exactly ``prior``; as observations pile
    up it converges on the recency-weighted ``ewma``.
    """
    base = _clamp(prior)
    return round(_clamp(base + confidence(observations) * (_clamp(ewma) - base)), 4)


def classify_fitness(value: float) -> str:
    """Lifecycle bucket for a fitness value."""
    if value >= ELITE_AT:
        return "elite"
    if value < PROBATION_BELOW:
        return "probationary"
    return "stable"


def trait_accuracy(traits: Mapping[str, Any], verdict: Any) -> Optional[float]:
    """Accuracy for one stance (``approve``/``reject``/``human_review``).

    ``None`` when the stance is unknown or was never observed on that stance.
    """
    key = stance_of(verdict)
    if key is None:
        return None
    trait = (traits or {}).get(key) or {}
    total = int(trait.get("observations", 0))
    if total <= 0:
        return None
    return round(int(trait.get("agreements", 0)) / total, 4)


def empty_genome(agent_id: str, *, generation: int = 1,
                 parent: Optional[str] = None) -> Dict[str, Any]:
    """A fresh, fully-populated genome row for ``agent_id``."""
    return {
        "agent_id": str(agent_id),
        "generation": int(generation),
        "parent": parent,
        "observations": 0,
        "agreements": 0,
        "dissent": 0,
        "unscored": 0,
        "streak": 0,
        "best_streak": 0,
        "ewma": NEUTRAL_FITNESS,
        "traits": {v: {"observations": 0, "agreements": 0} for v in FINAL_VERDICTS},
        "last_stance": None,
        "last_final": None,
        "fitness": NEUTRAL_FITNESS,
        "status": classify_fitness(NEUTRAL_FITNESS),
        "retired": False,
        "history": [],
    }


class GenomeV2:
    """In-memory genome: observes judgements, evolves members.

    Deterministic by construction — events are numbered with a counter instead
    of a timestamp, and nothing here touches the clock, the disk or the network.
    """

    def __init__(self, *, alpha: float = DEFAULT_ALPHA) -> None:
        self.alpha = _clamp(alpha)
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._seq = 0

    # ── registry ─────────────────────────────────────────────────────────
    def ensure(self, agent_id: str) -> Dict[str, Any]:
        """Return the (mutable) row for ``agent_id``, creating it if needed."""
        row = self._agents.get(str(agent_id))
        if row is None:
            row = empty_genome(agent_id)
            self._agents[str(agent_id)] = row
        return row

    # ── learning ─────────────────────────────────────────────────────────
    def observe(self, agent_id: str, member_verdict: Any,
                final_verdict: Any) -> Dict[str, Any]:
        """Fold one member judgement into that member's genome."""
        row = self.ensure(agent_id)
        self._seq += 1
        final_key = stance_of(final_verdict)
        matched = agreement(member_verdict, final_verdict)

        row["last_stance"] = str(member_verdict or "")
        row["last_final"] = final_key

        if matched is None:
            row["unscored"] = int(row["unscored"]) + 1
            event = "unscored"
        else:
            sample = 1.0 if matched else 0.0
            row["observations"] = int(row["observations"]) + 1
            if row["observations"] == 1:
                row["ewma"] = round(sample, 6)      # anchor on the first sample
            else:
                row["ewma"] = ewma_update(row["ewma"], sample, self.alpha)
            if matched:
                row["agreements"] = int(row["agreements"]) + 1
                row["streak"] = int(row["streak"]) + 1
                row["best_streak"] = max(int(row["best_streak"]), int(row["streak"]))
            else:
                row["dissent"] = int(row["dissent"]) + 1
                row["streak"] = 0
            if final_key is not None:
                trait = row["traits"][final_key]
                trait["observations"] = int(trait["observations"]) + 1
                trait["agreements"] = int(trait["agreements"]) + (1 if matched else 0)
            event = "agreement" if matched else "dissent"

        row["fitness"] = fitness(int(row["observations"]), float(row["ewma"]))
        row["status"] = classify_fitness(float(row["fitness"]))
        row["history"].append({
            "seq": self._seq, "event": event,
            "stance": row["last_stance"], "final": final_key,
        })
        if len(row["history"]) > HISTORY_LIMIT:
            del row["history"][:len(row["history"]) - HISTORY_LIMIT]
        return dict(row)

    def observe_council(self, stances: Mapping[str, Any],
                        final_verdict: Any) -> List[Dict[str, Any]]:
        """Record every member of one council round; returns their snapshots."""
        return [self.observe(agent_id, stance, final_verdict)
                for agent_id, stance in dict(stances or {}).items()]

    # ── evolution ────────────────────────────────────────────────────────
    def mutate(self, agent_id: str, note: str = "") -> Dict[str, Any]:
        """Re-train: reset the stats and bump the generation, keeping lineage."""
        row = self.ensure(agent_id)
        self._seq += 1
        generation = int(row["generation"]) + 1
        fresh = empty_genome(agent_id, generation=generation, parent=str(agent_id))
        fresh["history"] = [{
            "seq": self._seq, "event": "mutation",
            "note": str(note), "from_generation": generation - 1,
        }]
        self._agents[str(agent_id)] = fresh
        return dict(fresh)

    def retire(self, agent_id: str, note: str = "") -> Dict[str, Any]:
        """Take an agent out of the rotation (history is preserved)."""
        row = self.ensure(agent_id)
        self._seq += 1
        row["retired"] = True
        row["history"].append({"seq": self._seq, "event": "retired",
                               "note": str(note)})
        return dict(row)

    def revive(self, agent_id: str, note: str = "") -> Dict[str, Any]:
        """Put a retired agent back into the rotation."""
        row = self.ensure(agent_id)
        self._seq += 1
        row["retired"] = False
        row["history"].append({"seq": self._seq, "event": "revived",
                               "note": str(note)})
        return dict(row)

    # ── views ────────────────────────────────────────────────────────────
    def snapshot(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """A copy of ``agent_id``'s row, or ``None`` if never seen."""
        row = self._agents.get(str(agent_id))
        return dict(row) if row is not None else None

    def rank(self, *, include_retired: bool = False,
             limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Every agent, best fitness first (ties: more evidence, then id)."""
        rows = [dict(r) for r in self._agents.values()
                if include_retired or not r["retired"]]
        rows.sort(key=lambda r: (-float(r["fitness"]), -int(r["observations"]),
                                 str(r["agent_id"])))
        if limit is not None:
            return rows[:max(0, int(limit))]
        return rows

    def leaders(self, n: int = 3) -> List[Dict[str, Any]]:
        """The ``n`` best non-retired agents."""
        return self.rank(limit=n)

    def probationary(self) -> List[Dict[str, Any]]:
        """Non-retired agents below the probation fitness."""
        return [r for r in self.rank() if r["status"] == "probationary"]

    def advise(self, agent_id: str) -> Dict[str, Any]:
        """Recommend what to do with an agent, from its own evidence."""
        row = self.snapshot(agent_id)
        if row is None:
            return {"agent_id": str(agent_id), "action": "unknown",
                    "reason": "no observations yet", "fitness": NEUTRAL_FITNESS,
                    "observations": 0}
        observations = int(row["observations"])
        value = float(row["fitness"])
        if bool(row["retired"]):
            action, reason = "revise", "retired — revive only if needed again"
        elif observations < MIN_OBSERVATIONS:
            action, reason = "observe", f"only {observations} observation(s)"
        elif value >= ELITE_AT:
            action, reason = "promote", "fitness at or above the elite bar"
        elif value < PROBATION_BELOW:
            action, reason = "retrain", "fitness below probation — mutate"
        else:
            action, reason = "keep", "fitness inside the stable band"
        return {"agent_id": str(agent_id), "action": action, "reason": reason,
                "fitness": value, "observations": observations}

    def stats(self) -> Dict[str, Any]:
        """Aggregate counters for a dashboard/health endpoint."""
        rows = list(self._agents.values())
        alive = [r for r in rows if not r["retired"]]
        observations = sum(int(r["observations"]) for r in rows)
        mean = (round(sum(float(r["fitness"]) for r in alive) / len(alive), 4)
                if alive else NEUTRAL_FITNESS)
        return {
            "agents": len(rows),
            "active": len(alive),
            "retired": len(rows) - len(alive),
            "elite": sum(1 for r in alive if r["status"] == "elite"),
            "probationary": sum(1 for r in alive if r["status"] == "probationary"),
            "observations": observations,
            "mean_fitness": mean,
        }

    # ── portability ──────────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        """Whole genome as a JSON-ready dict."""
        return {"version": 2, "alpha": self.alpha, "seq": self._seq,
                "agents": {k: dict(v) for k, v in self._agents.items()}}

    @classmethod
    def from_dict(cls, payload: Optional[Mapping[str, Any]]) -> "GenomeV2":
        """Rebuild a genome from :meth:`to_dict` output (tolerant of junk)."""
        data = dict(payload or {})
        genome = cls(alpha=float(data.get("alpha", DEFAULT_ALPHA) or DEFAULT_ALPHA))
        genome._seq = int(data.get("seq", 0) or 0)
        for agent_id, row in dict(data.get("agents") or {}).items():
            if not isinstance(row, Mapping):
                continue
            base = empty_genome(agent_id)
            base.update({k: v for k, v in row.items() if k != "traits"})
            traits = row.get("traits")
            if isinstance(traits, Mapping):
                for verdict in FINAL_VERDICTS:
                    trait = traits.get(verdict)
                    if isinstance(trait, Mapping):
                        base["traits"][verdict] = {
                            "observations": int(trait.get("observations", 0) or 0),
                            "agreements": int(trait.get("agreements", 0) or 0),
                        }
            base["history"] = list(row.get("history") or [])
            genome._agents[str(agent_id)] = base
        return genome


# ── shared default instance (used by the council engine) ─────────────────────
_DEFAULT: Optional[GenomeV2] = None


def get_genome_v2(*, reset: bool = False) -> GenomeV2:
    """The process-wide genome; creates it on first use (or on ``reset``)."""
    global _DEFAULT
    if _DEFAULT is None or reset:
        _DEFAULT = GenomeV2()
    return _DEFAULT


def reset_genome_v2() -> GenomeV2:
    """Drop the shared genome and return a fresh one (tests/ops)."""
    return get_genome_v2(reset=True)
