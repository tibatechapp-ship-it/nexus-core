"""Agent Genome v2 (v1.14.0) — judgement-accuracy evolution + task outcomes.

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

Second result source (P4.5) — **task outcomes**: the 20 framework agents do not
debate, they *run tasks*.  :meth:`GenomeV2.observe_outcome` folds a task's
success/failure (plus its duration and gate quality) into the same agent row as
a separate, independently-shrunk channel, and the headline fitness is the
confidence-weighted blend of both sources.  Council-only genomes never call it,
so their rows stay **byte-identical** to v1.14.0; a task-only agent (never seen
in council) gets a standing from its task record alone.  Duration is recorded
as dashboard evidence but never scored — only success and gate quality move
fitness.

Pure and hermetic: standard library only, no I/O, no clock, no randomness, no
database.  Persistence is ``to_dict`` / ``from_dict`` (JSON-ready), which keeps
the phone gate and CI able to exercise the whole model offline.

Disk persistence lives **outside** this module (:mod:`src.novamind.genome_store`,
which loads/saves/seeds).  It attaches through the opt-in
``set_persistence_hook`` observer — unset by default, so the model below stays
byte-identical until a caller asks for a saved genome.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional

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
    "blend_fitness",
    "classify_fitness",
    "confidence",
    "empty_genome",
    "evidence",
    "ewma_update",
    "fitness",
    "get_genome_v2",
    "observe_result",
    "reset_genome_v2",
    "set_genome_v2",
    "set_persistence_hook",
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


def evidence(row: Mapping[str, Any]) -> int:
    """Total scored observations across BOTH result sources.

    Council judgements (``observations``) plus task outcomes
    (``task_observations``).  For a council-only row this is exactly
    ``observations`` — rankings and advice thresholds therefore behave as
    before until a second source actually appears.
    """
    return int(row.get("observations", 0) or 0) + int(row.get("task_observations", 0) or 0)


def blend_fitness(judgement: float, judgement_conf: float,
                  task: float, task_conf: float) -> float:
    """Confidence-weighted blend of the two result sources, in [0, 1].

    A source with zero confidence (no observations yet) contributes nothing,
    so the other side wins outright; with no evidence on either side the
    result is exactly ``NEUTRAL_FITNESS``.  With ``task_conf == 0`` the result
    is ``round(judgement, 4)`` — and since :func:`fitness` already returns four
    decimals, a council-only genome stores the *identical* value it did before
    the task source existed (byte-for-byte back-compat).
    """
    total = max(0.0, float(judgement_conf)) + max(0.0, float(task_conf))
    if total <= 0.0:
        return NEUTRAL_FITNESS
    weighted = (float(judgement_conf) * _clamp(judgement)
                + float(task_conf) * _clamp(task))
    return round(weighted / total, 4)


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
        # ── second result source (P4.5): real task outcomes ──
        "task_observations": 0,
        "task_successes": 0,
        "task_ewma": NEUTRAL_FITNESS,
        "task_duration_avg": None,       # EWMA seconds, None until first timed run
        "task_last_ok": None,
        "task_last_duration": None,
        "task_last_quality": None,
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
    @staticmethod
    def _blended_fitness(row: Mapping[str, Any]) -> float:
        """Recompute the headline fitness from both result sources.

        Judgement observations and task outcomes each get their own
        confidence-shrunk fitness, then :func:`blend_fitness` merges them by
        evidence.  A row with **no** task outcomes takes the exact expression
        the pre-P4.5 code stored (``fitness(observations, ewma)``), so a
        council-only genome is byte-identical to v1.14.0.
        """
        j_obs = int(row["observations"])
        j_fit = fitness(j_obs, float(row["ewma"]))
        t_obs = int(row.get("task_observations", 0) or 0)
        if t_obs <= 0:
            return j_fit
        # NB: an explicit None check — `0.0 or NEUTRAL` would swallow a
        # legitimate all-failures EWMA of exactly 0.0.
        raw_ewma = row.get("task_ewma")
        t_ewma = NEUTRAL_FITNESS if raw_ewma is None else float(raw_ewma)
        t_fit = fitness(t_obs, t_ewma)
        return blend_fitness(j_fit, confidence(j_obs), t_fit, confidence(t_obs))

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
            # matched is not None only when BOTH stances were recognised, so
            # final_key is guaranteed set here (agreement() already checked it).
            trait = row["traits"][final_key]
            trait["observations"] = int(trait["observations"]) + 1
            trait["agreements"] = int(trait["agreements"]) + (1 if matched else 0)
            event = "agreement" if matched else "dissent"

        row["fitness"] = self._blended_fitness(row)
        row["status"] = classify_fitness(float(row["fitness"]))
        row["history"].append({
            "seq": self._seq, "event": event,
            "stance": row["last_stance"], "final": final_key,
        })
        if len(row["history"]) > HISTORY_LIMIT:
            del row["history"][:len(row["history"]) - HISTORY_LIMIT]
        _notify(self)
        return dict(row)

    def observe_outcome(self, agent_id: str, ok: bool, *,
                        duration: Optional[float] = None,
                        quality: Optional[float] = None,
                        task: str = "") -> Dict[str, Any]:
        """Fold one **task outcome** into that agent's genome (P4.5, second source).

        The 20 framework agents do not debate — they run tasks.  This channel
        scores what actually happened:

        * ``ok`` is the ground truth.  A failure is always a ``0.0`` sample,
          whatever a gate quality says — a failed task can never raise fitness.
        * ``quality`` (gate score in [0, 1]) *refines a success*: a clean pass
          (no quality given) samples ``1.0``; a pass that only barely cleared
          the gate samples its quality instead.
        * ``duration`` (seconds) is recorded as an EWMA of run times for the
          dashboard — **never** scored; speed is not correctness.

        Judgement fields (``last_stance`` / ``last_final`` / ``traits``) stay
        untouched — they describe council debate, not task work.  The headline
        fitness becomes the confidence-blended value of both sources.
        """
        row = self.ensure(agent_id)
        self._seq += 1
        passed = bool(ok)

        sample = 1.0 if passed else 0.0
        quality_value: Optional[float] = None
        if quality is not None:
            try:
                quality_value = round(_clamp(float(quality)), 6)
            except (TypeError, ValueError):
                quality_value = None
        if passed and quality_value is not None:
            sample = quality_value

        duration_value: Optional[float] = None
        if duration is not None:
            try:
                duration_value = max(0.0, float(duration))
            except (TypeError, ValueError):
                duration_value = None

        row["task_observations"] = int(row.get("task_observations", 0) or 0) + 1
        if passed:
            row["task_successes"] = int(row.get("task_successes", 0) or 0) + 1
        # NB: None check, not `or` — an all-failures EWMA of 0.0 is real data.
        raw_ewma = row.get("task_ewma")
        previous_ewma = NEUTRAL_FITNESS if raw_ewma is None else float(raw_ewma)
        if int(row["task_observations"]) == 1:
            row["task_ewma"] = round(sample, 6)     # anchor on the first outcome
        else:
            row["task_ewma"] = ewma_update(previous_ewma, sample, self.alpha)
        if duration_value is not None:
            # Durations are seconds — never clamped into [0, 1] like fitness.
            previous_avg = row.get("task_duration_avg")
            if previous_avg is None:
                row["task_duration_avg"] = round(duration_value, 4)
            else:
                a = self.alpha
                blended = (1.0 - a) * float(previous_avg) + a * duration_value
                row["task_duration_avg"] = round(max(0.0, blended), 4)
        row["task_last_ok"] = passed
        row["task_last_duration"] = duration_value
        row["task_last_quality"] = quality_value

        row["fitness"] = self._blended_fitness(row)
        row["status"] = classify_fitness(float(row["fitness"]))
        row["history"].append({
            "seq": self._seq, "event": "task", "ok": passed,
            "duration": duration_value, "quality": quality_value,
            "task": str(task),
        })
        if len(row["history"]) > HISTORY_LIMIT:
            del row["history"][:len(row["history"]) - HISTORY_LIMIT]
        _notify(self)
        return dict(row)

    def observe_result(self, result: Any, *, quality: Optional[float] = None,
                       task: str = "") -> Optional[Dict[str, Any]]:
        """Fold a framework ``AgentResult``-shaped object into the genome.

        Duck-typed on purpose (``agent`` / ``ok`` / ``duration_s``), so this
        works for :class:`src.core.types.AgentResult` without importing the
        framework layer — and for any tuple-shaped stand-in in tests.  Returns
        ``None`` when the object carries no usable agent id or ``ok`` flag
        (unscorable input must not poison the registry).
        """
        agent_id = getattr(result, "agent", None)
        ok = getattr(result, "ok", None)
        if not agent_id or ok is None:
            return None
        duration = getattr(result, "duration_s", None)
        return self.observe_outcome(str(agent_id), bool(ok), duration=duration,
                                    quality=quality, task=task)

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
        _notify(self)
        return dict(fresh)

    def retire(self, agent_id: str, note: str = "") -> Dict[str, Any]:
        """Take an agent out of the rotation (history is preserved)."""
        row = self.ensure(agent_id)
        self._seq += 1
        row["retired"] = True
        row["history"].append({"seq": self._seq, "event": "retired",
                               "note": str(note)})
        _notify(self)
        return dict(row)

    def revive(self, agent_id: str, note: str = "") -> Dict[str, Any]:
        """Put a retired agent back into the rotation."""
        row = self.ensure(agent_id)
        self._seq += 1
        row["retired"] = False
        row["history"].append({"seq": self._seq, "event": "revived",
                               "note": str(note)})
        _notify(self)
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
        rows.sort(key=lambda r: (-float(r["fitness"]), -evidence(r),
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
        """Recommend what to do with an agent, from its own evidence.

        The thresholds count :func:`evidence` (both result sources), so a
        task-only agent can earn ``promote``/``retrain`` without ever entering
        a council.  For council-only rows evidence == observations, which is
        exactly the pre-P4.5 behaviour.
        """
        row = self.snapshot(agent_id)
        if row is None:
            return {"agent_id": str(agent_id), "action": "unknown",
                    "reason": "no observations yet", "fitness": NEUTRAL_FITNESS,
                    "observations": 0, "evidence": 0}
        total = evidence(row)
        value = float(row["fitness"])
        if bool(row["retired"]):
            action, reason = "revise", "retired — revive only if needed again"
        elif total < MIN_OBSERVATIONS:
            action, reason = "observe", f"only {total} observation(s)"
        elif value >= ELITE_AT:
            action, reason = "promote", "fitness at or above the elite bar"
        elif value < PROBATION_BELOW:
            action, reason = "retrain", "fitness below probation — mutate"
        else:
            action, reason = "keep", "fitness inside the stable band"
        return {"agent_id": str(agent_id), "action": action, "reason": reason,
                "fitness": value, "observations": int(row["observations"]),
                "evidence": total}

    def stats(self) -> Dict[str, Any]:
        """Aggregate counters for a dashboard/health endpoint."""
        rows = list(self._agents.values())
        alive = [r for r in rows if not r["retired"]]
        observations = sum(int(r["observations"]) for r in rows)
        tasks = sum(int(r.get("task_observations", 0) or 0) for r in rows)
        mean = (round(sum(float(r["fitness"]) for r in alive) / len(alive), 4)
                if alive else NEUTRAL_FITNESS)
        return {
            "agents": len(rows),
            "active": len(alive),
            "retired": len(rows) - len(alive),
            "elite": sum(1 for r in alive if r["status"] == "elite"),
            "probationary": sum(1 for r in alive if r["status"] == "probationary"),
            "observations": observations,
            "task_observations": tasks,
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

    def adopt(self, other: "GenomeV2") -> "GenomeV2":
        """Take over ``other``'s state **in place** (keeps object identity).

        The council engine, the field loop and the gateway all hold a reference
        to the one shared genome, so restoring a saved genome must mutate that
        singleton rather than swap it for a new object (a swap would leave the
        other holders talking to the empty copy).  The state is deep-copied via
        a ``to_dict`` / ``from_dict`` round-trip so ``other`` stays untouched.
        """
        fresh = GenomeV2.from_dict(other.to_dict() if other is not None else None)
        self.alpha = fresh.alpha
        self._agents = fresh._agents
        self._seq = fresh._seq
        return self


# ── shared default instance (used by the council engine) ─────────────────────
_DEFAULT: Optional[GenomeV2] = None

#: Optional side-observer called after every mutation (persistence hook).
_HOOK: Optional[Callable[[GenomeV2], None]] = None


def _notify(genome: GenomeV2) -> None:
    """Run the persistence hook, if any.  Observability never breaks a caller."""
    hook = _HOOK
    if hook is None:
        return
    try:
        hook(genome)
    except Exception:  # pragma: no cover - defensive
        pass


def set_persistence_hook(hook: Optional[Callable[[GenomeV2], None]]) -> None:
    """Install (or clear with ``None``) the after-mutation observer.

    ``None`` is the default, which leaves behaviour byte-identical to the
    hook-free model — the genome stays pure until someone asks for persistence.
    """
    global _HOOK
    _HOOK = hook


def get_genome_v2(*, reset: bool = False) -> GenomeV2:
    """The process-wide genome; creates it on first use (or on ``reset``)."""
    global _DEFAULT
    if _DEFAULT is None or reset:
        _DEFAULT = GenomeV2()
    return _DEFAULT


def set_genome_v2(genome: GenomeV2) -> GenomeV2:
    """Make ``genome`` the process-wide instance (used when loading from disk)."""
    global _DEFAULT
    _DEFAULT = genome
    return genome


def reset_genome_v2() -> GenomeV2:
    """Drop the shared genome and return a fresh one (tests/ops)."""
    return get_genome_v2(reset=True)


def observe_result(result: Any, *, quality: Optional[float] = None,
                   task: str = "",
                   genome: Optional[GenomeV2] = None) -> Optional[Dict[str, Any]]:
    """Fold a task ``AgentResult`` into the shared genome (P4.5 convenience).

    One-line wiring for callers that hold a framework result:
    ``observe_result(agent.run(...))``.  Pass ``genome=`` to target another
    instance (tests); returns the updated snapshot, or ``None`` when the
    result carried no usable agent id / ``ok`` flag.
    """
    target = genome if genome is not None else get_genome_v2()
    return target.observe_result(result, quality=quality, task=task)
