"""Training engine — run a full training plan and decide graduation (P3).

Design notes (why this is a new layer instead of a rewrite):

* The legacy runner in ``novamind.core.training`` scores with ``random.gauss``,
  so the same agent can pass one run and fail the next.  This engine takes an
  **injectable evaluator** which defaults to a *deterministic* scorer, so a run
  is reproducible and the graduation gate can be asserted on in a test.
* The curriculum comes from the real plans (``get_training_plan(spec)``), with
  the agent's own skill tags from its manifest appended as extra modules — so a
  manifest change alters training without a second source of truth.
* Graduation has a **hard floor** (:data:`~.models.GRADUATION_MIN_SCORE`).
  A plan cannot lower it, and a certificate is never issued below it.
* Everything external — the manifest, the genome, the certificate signer — is
  imported lazily and guarded, so the engine works on a bare phone install.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .models import (
    GRADUATION_MIN_SCORE,
    TrainingRun,
    verdict_for,
)
from .store import TrainingStore, get_store

#: ``evaluator(agent_id, skill, index, *, quality, salt) -> score in [0, 1]``
Evaluator = Callable[..., float]

#: A module scoring below this is a *critical* failure (blocks graduation).
CRITICAL_FAILURE_BELOW = 0.50

#: Fallback module floor, matching ``TrainingModule.min_score``.
DEFAULT_MODULE_MIN_SCORE = 0.70

#: Default spread of the deterministic evaluator around the trainer quality.
_DEFAULT_SPREAD = 0.12
_DEFAULT_QUALITY = 0.85

#: Skills used only when neither the manifest nor the plan loader is available.
_FALLBACK_SKILLS: Tuple[str, ...] = (
    "understand_nova_philosophy", "military_protocol", "secure_communication",
    "hallucination_awareness", "quality_standards", "isolation_rules",
    "waste_handling", "self_monitoring", "simulation_basics",
    "acceptance_test", "team_exercise",
)


@dataclass(frozen=True)
class ModuleSpec:
    """One unit of training: what it is called, how long, and its own floor."""

    name: str
    hours: float = 1.0
    min_score: float = DEFAULT_MODULE_MIN_SCORE
    source: str = "plan"

    def to_dict(self) -> Dict[str, Any]:
        """JSON-friendly view."""
        return {
            "name": self.name,
            "hours": self.hours,
            "min_score": self.min_score,
            "source": self.source,
        }


def deterministic_evaluator(
    agent_id: str, skill: str, index: int, *,
    quality: float = _DEFAULT_QUALITY, salt: str = "",
) -> float:
    """Score one module deterministically from ``(agent_id, skill, salt)``.

    Re-running the same agent on the same curriculum yields the same scores,
    which is what makes the training gate testable and reviewable.
    """
    digest = hashlib.sha256(
        f"{salt}|{agent_id}|{skill}|{index}".encode("utf-8")
    ).digest()
    # Map the first four bytes onto [-1, 1) without float rounding surprises.
    raw = int.from_bytes(digest[:4], "big") / float(1 << 32)
    offset = (raw * 2.0) - 1.0
    score = float(quality) + offset * _DEFAULT_SPREAD
    return round(min(1.0, max(0.0, score)), 4)


def normalize_tag(tag: str) -> str:
    """Normalise a manifest skill tag onto the plan's snake_case naming."""
    return re.sub(r"[^a-z0-9]+", "_", str(tag).strip().lower()).strip("_")


def _manifest(agent_id: str) -> Any:
    """The agent's manifest, or ``None`` when unavailable."""
    for module_name in ("agents.manifest", "src.agents.manifest"):
        try:
            import importlib

            module = importlib.import_module(module_name)
            return module.get_manifest(str(agent_id))
        except ImportError:
            continue
        except Exception:
            return None
    return None


def _spec_for(agent_id: str, spec: Optional[str]) -> str:
    """Resolve the training spec for an agent (explicit wins over the manifest)."""
    if spec:
        return str(spec)
    manifest = _manifest(agent_id)
    resolved = getattr(manifest, "spec", None) if manifest is not None else None
    return str(resolved) if resolved else "default"


def _plan_modules(spec: str) -> List[ModuleSpec]:
    """The curriculum for ``spec`` from the real training plans."""
    modules: List[ModuleSpec] = []
    try:  # pragma: no cover - depends on the deployment's import layout
        import importlib

        plans = None
        for module_name in (
            "novamind.core.training.training_plans",
            "src.novamind.core.training.training_plans",
        ):
            try:
                plans = importlib.import_module(module_name)
                break
            except ImportError:
                continue
        if plans is not None:
            plan = plans.get_training_plan(spec)
            for module in plan.modules:
                modules.append(ModuleSpec(
                    name=str(module.name),
                    hours=float(getattr(module, "hours", 1) or 1),
                    min_score=float(
                        getattr(module, "min_score", DEFAULT_MODULE_MIN_SCORE)
                    ),
                    source="plan",
                ))
    except Exception:
        modules = []
    if not modules:
        modules = [ModuleSpec(name=name) for name in _FALLBACK_SKILLS]
    return modules


class TrainingEngine:
    """Runs curricula, decides graduation, records runs and certifies graduates."""

    def __init__(
        self,
        *,
        store: Optional[TrainingStore] = None,
        evaluator: Optional[Evaluator] = None,
        clock: Optional[Callable[[], float]] = None,
        min_score: float = GRADUATION_MIN_SCORE,
        feed_genome: bool = True,
        field_loop: bool = True,
    ) -> None:
        self._store = store
        self.evaluator: Evaluator = evaluator or deterministic_evaluator
        self._clock = clock or time.time
        # The graduation floor is a hard floor: a caller (or a plan) may raise
        # the bar but never lower it below the published constant.
        self.min_score = max(float(min_score), GRADUATION_MIN_SCORE)
        self.feed_genome = bool(feed_genome)
        # The field loop (P4) turns every run into a lesson and evolves the
        # genome.  It is the default path; turning it off falls back to the P3
        # one-way genome feed, so every earlier caller behaves as before.
        self.field_loop = bool(field_loop)
        self._field: Any = None
        self._lock = threading.Lock()

    # ── helpers ──────────────────────────────────────────────────────────
    @property
    def store(self) -> TrainingStore:
        """The backing store (created lazily and cached)."""
        if self._store is None:
            self._store = get_store()
        return self._store

    def modules_for(
        self, agent_id: str, spec: Optional[str] = None
    ) -> Tuple[ModuleSpec, ...]:
        """The full curriculum: plan modules plus the agent's own skill tags."""
        resolved = _spec_for(agent_id, spec)
        modules = _plan_modules(resolved)
        seen = {m.name for m in modules}
        manifest = _manifest(agent_id)
        for tag in tuple(getattr(manifest, "skills", ()) or ()):
            name = normalize_tag(tag)
            if name and name not in seen:
                seen.add(name)
                modules.append(ModuleSpec(name=name, source="manifest"))
        return tuple(modules)

    def plan(self, agent_id: str, spec: Optional[str] = None) -> Dict[str, Any]:
        """A read-only description of the curriculum an agent would run."""
        resolved = _spec_for(agent_id, spec)
        modules = self.modules_for(agent_id, spec)
        latest = self.store.latest_run(agent_id)
        return {
            "agent_id": str(agent_id),
            "spec": resolved,
            "modules": [m.to_dict() for m in modules],
            "module_count": len(modules),
            "total_hours": round(sum(m.hours for m in modules), 2),
            "min_score": self.min_score,
            "critical_failure_below": CRITICAL_FAILURE_BELOW,
            "latest_run": latest.to_dict() if latest else None,
        }

    # ── the run ──────────────────────────────────────────────────────────
    def train(
        self, agent_id: str, spec: Optional[str] = None, *,
        quality: float = _DEFAULT_QUALITY, salt: str = "",
    ) -> TrainingRun:
        """Train one agent and record the outcome.

        A certificate is issued **only** when the run graduates *and* its final
        score meets :data:`GRADUATION_MIN_SCORE`.
        """
        agent_id = str(agent_id)
        resolved = _spec_for(agent_id, spec)
        modules = self.modules_for(agent_id, spec)
        started = float(self._clock())

        phases: List[Dict[str, Any]] = []
        for index, module in enumerate(modules):
            score = float(
                self.evaluator(
                    agent_id, module.name, index, quality=quality, salt=salt
                )
            )
            score = round(min(1.0, max(0.0, score)), 4)
            phases.append({
                "skill": module.name,
                "index": index,
                "hours": module.hours,
                "min_score": module.min_score,
                "source": module.source,
                "score": score,
                "passed": score >= module.min_score,
                "critical": score < CRITICAL_FAILURE_BELOW,
            })

        total_hours = sum(p["hours"] for p in phases) or 1.0
        passed = [p for p in phases if p["passed"]]
        completion_rate = round(len(passed) / len(phases), 4) if phases else 0.0
        training_score = round(
            sum(p["score"] * p["hours"] for p in phases) / total_hours, 4
        ) if phases else 0.0
        critical = [p for p in phases if p["critical"]]

        # The gate reads both halves: how much of the curriculum was completed
        # and how good the work was.  It can never exceed the work quality.
        gate_score = round(
            min(0.5 * completion_rate + 0.5 * training_score, training_score), 4
        ) if phases else 0.0
        final_score = round(0.5 * training_score + 0.5 * gate_score, 4) if phases else 0.0

        graduated = (
            completion_rate >= 0.8
            and training_score >= self.min_score
            and not critical
        )
        verdict = verdict_for(
            graduated, final_score,
            completion_rate=completion_rate, critical=bool(critical),
        )
        certified = bool(graduated and final_score >= self.min_score)

        run = TrainingRun(
            run_id=f"tr_{uuid.uuid4().hex[:12]}",
            agent_id=agent_id,
            spec=resolved,
            started_at=started,
            finished_at=float(self._clock()),
            completion_rate=completion_rate,
            training_score=training_score,
            gate_score=gate_score,
            final_score=final_score,
            verdict=verdict,
            certified=certified,
            phases=tuple(phases),
            detail={
                "quality": float(quality),
                "salt": str(salt),
                "modules_total": len(phases),
                "modules_passed": len(passed),
                "critical_failures": [p["skill"] for p in critical],
                "min_score": self.min_score,
                "total_hours": round(total_hours, 2),
            },
        )

        with self._lock:
            self.store.save_run(run)
            if certified:
                self._issue_certificate(run)

        if self.field_loop:
            self._run_field(run)
        elif self.feed_genome:
            self._feed_genome(run)
        return run

    def train_batch(
        self, agent_ids: Sequence[str], spec: Optional[str] = None, *,
        quality: float = _DEFAULT_QUALITY, salt: str = "",
    ) -> List[TrainingRun]:
        """Train several agents, continuing past an individual failure."""
        runs: List[TrainingRun] = []
        for agent_id in agent_ids:
            try:
                runs.append(self.train(agent_id, spec, quality=quality, salt=salt))
            except Exception as exc:  # pragma: no cover - defensive
                now = float(self._clock())
                runs.append(TrainingRun(
                    run_id=f"tr_err_{uuid.uuid4().hex[:8]}",
                    agent_id=str(agent_id),
                    spec=str(spec or "default"),
                    started_at=now, finished_at=now,
                    completion_rate=0.0, training_score=0.0,
                    gate_score=0.0, final_score=0.0,
                    verdict="failed", certified=False,
                    detail={"error": str(exc)},
                ))
        return runs

    # ── certificate ──────────────────────────────────────────────────────
    def _issue_certificate(self, run: TrainingRun) -> Dict[str, Any]:
        """Record a certificate for a graduated run (never called below the floor)."""
        certificate_id = "cert_" + hashlib.sha256(
            f"{run.run_id}|{run.agent_id}|{run.final_score}".encode("utf-8")
        ).hexdigest()[:16]
        payload: Dict[str, Any] = {
            "certificate_id": certificate_id,
            "agent_id": run.agent_id,
            "run_id": run.run_id,
            "spec": run.spec,
            "score": run.final_score,
            "issued_at": run.finished_at,
        }
        return self.store.issue_certificate(
            certificate_id=certificate_id, run=run,
            signature=_sign_certificate(payload), payload=payload,
        )

    # ── genome ───────────────────────────────────────────────────────────
    def _feed_genome(self, run: TrainingRun) -> None:
        """Score the agent's *self-assessment*: did it claim more than it proved?

        The agent's stance is what it said about itself (its score cleared the
        bar), the ground truth is the gate's decision.  Claiming readiness and
        failing the gate is a dissent, and the genome records it.
        """
        try:  # pragma: no cover - genome is optional
            import importlib

            genome_v2 = None
            # ``src.`` first — same spelling as the Council engine, so both
            # share ONE process-wide genome (one file, two names = two copies).
            for module_name in ("src.novamind.genome_v2",
                                "novamind.genome_v2"):
                try:
                    genome_v2 = importlib.import_module(module_name)
                    break
                except ImportError:
                    continue
            if genome_v2 is None:
                return
            floor = run.detail.get("min_score", GRADUATION_MIN_SCORE)
            claimed = "yes" if run.training_score >= float(floor) else "no"
            truth = "yes" if run.certified else "no"
            genome_v2.get_genome_v2().observe(run.agent_id, claimed, truth)
        except Exception:
            return

    # ── field loop (P4) ──────────────────────────────────────────────────
    def field(self) -> Optional[Any]:
        """The field loop bound to this engine, or ``None`` when unavailable.

        The loop lives beside the training database so a run with its own store
        keeps its own lessons (and tests stay hermetic).  ``feed_genome`` gates
        the genome half — with it off the loop only records lessons, which is
        exactly what a hermetic test wants.  ``field_loop=False`` by-passes the
        loop entirely, restoring the plain P3 behaviour.
        """
        if not self.field_loop:
            return None
        if self._field is None:
            try:
                from .field import FieldLoop, default_lesson_db_path, field_enabled

                if not field_enabled():
                    return None
                self._field = FieldLoop(
                    lesson_db=default_lesson_db_path(self.store.path),
                    genome_enabled=self.feed_genome,
                )
            except Exception:
                return None
        return self._field

    def _run_field(self, run: TrainingRun) -> None:
        """Close the loop for one run (never let the feed break a training run)."""
        loop = self.field()
        if loop is None:
            return
        try:
            loop.tick(run)
        except Exception:
            return

    # ── field views (delegate, tolerant of a missing loop) ───────────────
    def field_stats(self) -> Dict[str, Any]:
        """Loop counters (``{}`` when the loop is unavailable)."""
        loop = self.field()
        if loop is None:
            return {}
        try:
            return dict(loop.stats())
        except Exception:
            return {}

    def lessons(self, agent_id: Optional[str] = None, limit: int = 50) -> List[Any]:
        """Lessons the loop has absorbed (empty when it is unavailable)."""
        loop = self.field()
        if loop is None:
            return []
        try:
            return list(loop.lessons(agent_id, limit=limit))
        except Exception:
            return []

    def evolve(self) -> List[Dict[str, Any]]:
        """Run an evolution pass now (empty when the loop is unavailable)."""
        loop = self.field()
        if loop is None:
            return []
        try:
            return list(loop.evolve())
        except Exception:
            return []

    def fitness(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Per-agent genome standings (empty when the loop is unavailable)."""
        loop = self.field()
        if loop is None:
            return []
        try:
            return list(loop.fitness(limit))
        except Exception:
            return []


_ENGINE: Optional[TrainingEngine] = None
_ENGINE_LOCK = threading.Lock()

#: Cached certificate signer; ``False`` means "signing is not available here".
_SIGNER: Any = None


def _sign_certificate(payload: Dict[str, Any]) -> str:
    """Sign a certificate payload, or return ``""`` when signing is unavailable.

    Ed25519 is used when ``cryptography`` really works here (the signer persists
    its key under ``~/.config/nexus/keys`` so verification survives restarts);
    otherwise the certificate is stored unsigned rather than invented.
    """
    global _SIGNER
    if _SIGNER is False:
        return ""
    if _SIGNER is None:
        try:
            import importlib

            # Probe the primitive we actually use, not just the package: on
            # Termux ``cryptography`` can be installed yet fail to load its
            # native backend, and the signer would print a warning to stdout.
            try:
                importlib.import_module(
                    "cryptography.hazmat.primitives.asymmetric.ed25519"
                )
            except Exception:
                _SIGNER = False
                return ""
            try:
                module = importlib.import_module("certification.signer")
            except ImportError:
                module = importlib.import_module("src.certification.signer")
            _SIGNER = module.Signer()
        except Exception:
            _SIGNER = False
            return ""
    try:
        return str(_SIGNER.sign(dict(payload)))
    except Exception:
        return ""


def reset_signer() -> None:
    """Drop the cached signer (tests only)."""
    global _SIGNER
    _SIGNER = None


def get_engine(**kwargs: Any) -> TrainingEngine:
    """Process-wide engine (tests pass ``store=`` / ``evaluator=``)."""
    global _ENGINE
    if kwargs:
        return TrainingEngine(**kwargs)
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = TrainingEngine()
        return _ENGINE


def reset_engine() -> None:
    """Drop the cached singleton (tests only)."""
    global _ENGINE
    with _ENGINE_LOCK:
        _ENGINE = None
