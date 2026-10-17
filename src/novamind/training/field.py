"""Field loop (P4) — every run becomes a lesson, feeds the genome, evolves it.

The loop closes the training cycle:

    run ──▶ lesson ──▶ genome observation ──▶ evolution

* **run → lesson** — the run's own evidence (how much of the curriculum was
  completed, the final score and *which* modules failed) is distilled into a
  :class:`~learning.lesson.Lesson` and merged into a
  :class:`~learning.lesson_store.LessonStore`.  A repeated failure on the same
  module consolidates into a single lesson whose evidence and confidence grow
  instead of piling up duplicates.
* **lesson → genome** — the agent's *self-assessment* (did it claim readiness?)
  is compared with the gate's decision (was it actually certified?) and folded
  into ``genome_v2``, the judgement-accuracy signal the genome scores.
* **genome → evolution** — :meth:`FieldLoop.evolve` reads each member's own
  evidence and **mutates** (re-trains) the probationary ones.  Mutation resets
  the observation count, which doubles as the cooldown: an agent can never be
  mutated twice without new evidence, so evolution cannot thrash.

One lesson store **per agent**: a store merges lessons by principle similarity,
which is desirable *within* an agent and wrong *across* agents — a cross-agent
merge would re-attribute one agent's lesson to whichever agent happened to be
most common in the group.

Everything external (the genome, the learning layer) is imported lazily and
guarded, so the loop degrades gracefully instead of taking a training run down.
"""
from __future__ import annotations

import importlib
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .engine import CRITICAL_FAILURE_BELOW
from .models import GRADUATION_MIN_SCORE, TrainingRun
from .store import default_db_path

#: Master switch for the loop (``NEXUS_TRAINING_FIELD=0`` disables the field feed).
FIELD_ENV = "NEXUS_TRAINING_FIELD"

#: Fitness of an agent with no evidence yet (mirrors ``genome_v2``).
_NEUTRAL_FITNESS = 0.5

#: Explicit lesson-database path for the field loop.
LESSON_DB_ENV = "NEXUS_TRAINING_LESSONS_DB"

#: Confidence band a single lesson starts in (repeats raise it via the merge).
_MIN_CONFIDENCE = 0.5
_MAX_CONFIDENCE = 0.95

#: Bounds so a caller cannot ask for an unbounded listing.
_MIN_LIMIT = 1
_MAX_LIMIT = 500


def default_lesson_db_path(training_db: Optional[Path] = None) -> Path:
    """Resolve the field loop's lesson database.

    ``$NEXUS_TRAINING_LESSONS_DB`` wins; otherwise the lessons live beside the
    training database (``training.db`` → ``lessons.db``), so a run configured
    with its own training DB also gets its own lesson DB — and tests that use a
    throwaway store stay hermetic.
    """
    explicit = os.environ.get(LESSON_DB_ENV)
    if explicit:
        return Path(explicit)
    base = Path(training_db) if training_db is not None else default_db_path()
    return base.with_name("lessons.db")


def field_enabled() -> bool:
    """Whether ``$NEXUS_TRAINING_FIELD`` leaves the field feed on (default: on)."""
    return os.environ.get(FIELD_ENV, "1").strip().lower() not in {
        "0", "false", "no", "off",
    }


def _clamp_limit(limit: int) -> int:
    """Clamp a listing limit into the supported range."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return _MAX_LIMIT
    return max(_MIN_LIMIT, min(value, _MAX_LIMIT))


def _learning(name: str) -> Any:
    for module_name in (f"learning.{name}", f"src.learning.{name}"):
        try:
            return importlib.import_module(module_name)
        except ImportError:
            continue
        except Exception:
            return None
    return None


def lesson_from_run(run: TrainingRun, *, now: Optional[float] = None) -> Any:
    """Distil one training run into a lesson, or ``None`` without the layer.

    The principle is deliberately *stable* for a given failure mode, so a repeat
    merges into the existing lesson instead of creating a twin.
    """
    lesson_module = _learning("lesson")
    if lesson_module is None:
        return None
    Lesson = lesson_module.Lesson
    Outcome = lesson_module.Outcome

    spec = str(run.spec or "default")
    phases = tuple(run.phases)
    total = int(run.detail.get("modules_total") or len(phases) or 0)
    passed = int(run.detail.get("modules_passed") or 0)
    critical = tuple(str(name) for name in (run.detail.get("critical_failures") or ()))
    failing = tuple(
        str(p["skill"]) for p in phases if not p.get("passed", False)
    ) or tuple(
        str(p["skill"]) for p in phases
        if float(p.get("score", 1.0)) < CRITICAL_FAILURE_BELOW
    )

    floor = float(run.detail.get("min_score", GRADUATION_MIN_SCORE))
    span = max(1e-9, 1.0 - floor)
    incomplete = max(0.0, 1.0 - float(run.completion_rate))

    if run.certified:
        outcome = Outcome.SUCCESS
        principle = f"Finish every {spec} module before asking to be evaluated"
        margin = (float(run.final_score) - floor) / span
        strength = max(0.0, min(1.0, margin))
    elif critical:
        outcome = Outcome.FAILURE
        principle = (
            f"Do not claim {spec} readiness while {critical[0]} is below the bar"
        )
        strength = incomplete
    else:
        outcome = Outcome.FAILURE if run.verdict == "failed" else Outcome.PARTIAL
        principle = f"Complete the whole {spec} curriculum, not just the strong modules"
        strength = incomplete

    confidence = round(
        min(_MAX_CONFIDENCE, _MIN_CONFIDENCE + 0.45 * strength), 4
    )

    evidence: List[str] = [f"run:{run.run_id}"]
    evidence.extend(f"critical:{name}" for name in critical)
    evidence.extend(f"failed:{name}" for name in failing)
    if not critical and not failing:
        evidence.append(f"passed:{passed}/{total}")

    tags = {
        "training", spec, f"verdict:{run.verdict}", f"outcome:{outcome.value}",
    }
    tags.update(f"module:{name}" for name in (critical or failing))

    return Lesson(
        id=str(run.run_id),
        principle=principle,
        context=(
            f"{run.agent_id} · {spec} · {passed}/{total} modules passed · "
            f"score {float(run.final_score):.4f} · {run.verdict}"
        ),
        confidence=confidence,
        evidence=tuple(evidence),
        source_outcome=outcome,
        created_at=float(now if now is not None else (run.finished_at or time.time())),
        agent_role=str(run.agent_id),
        tags=frozenset(tags),
    )


def _lesson_view(lesson: Any) -> Optional[Dict[str, Any]]:
    """JSON-ready view of a lesson (``None`` passes through)."""
    if lesson is None:
        return None
    to_dict = getattr(lesson, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    return {
        "id": str(getattr(lesson, "id", "")),
        "principle": str(getattr(lesson, "principle", "")),
        "confidence": float(getattr(lesson, "confidence", 0.0)),
        "agent_role": str(getattr(lesson, "agent_role", "")),
    }


class FieldLoop:
    """Turns runs into lessons, feeds the genome, and evolves it."""

    def __init__(
        self,
        *,
        genome: Any = None,
        lesson_db: Optional[Path] = None,
        clock: Optional[Any] = None,
        genome_enabled: bool = True,
    ) -> None:
        self._genome = genome
        self._clock = clock or time.time
        self.genome_enabled = bool(genome_enabled)
        self._stores: Dict[str, Any] = {}          # agent_id → LessonStore
        self._absorbed = 0
        self._merged = 0
        self._mutations: List[str] = []
        self._ticks = 0
        self._last_tick: Optional[Dict[str, Any]] = None
        self._lock = threading.RLock()
        self._lesson_db_path = Path(lesson_db) if lesson_db is not None else None
        self._database = self._open_database(lesson_db)

    # ── wiring ───────────────────────────────────────────────────────────
    def _open_database(self, path: Optional[Path]) -> Any:
        """Open the lesson DB and restore any lessons it already holds."""
        if path is None:
            return None
        module = _learning("lesson_store")
        if module is None:
            return None
        try:
            database = module.LessonDatabase(str(path))
            self._lesson_db_path = Path(path)
            for lesson in database.load():
                store = self._store_for(str(lesson.agent_role))
                if store is not None:
                    store.add(lesson)
            return database
        except Exception:
            return None

    def _genome_obj(self) -> Any:
        """The genome to feed (injected, else the process-wide one)."""
        if self._genome is not None:
            return self._genome
        # ``src.`` first: the Council engine imports that spelling, and two
        # spellings of one file = two module copies = two genomes.
        for module_name in ("src.novamind.genome_v2", "novamind.genome_v2"):
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                continue
            except Exception:
                return None
            return module.get_genome_v2()
        return None

    def _store_for(self, agent_id: str) -> Any:
        """The per-agent lesson store, created on first use."""
        key = str(agent_id)
        store = self._stores.get(key)
        if store is None:
            module = _learning("lesson_store")
            if module is None:
                return None
            store = module.LessonStore()
            self._stores[key] = store
        return store

    # ── the loop ─────────────────────────────────────────────────────────
    def absorb(self, run: TrainingRun) -> Any:
        """run → lesson: distil, merge into the agent's store, persist."""
        lesson = lesson_from_run(run, now=float(self._clock()))
        if lesson is None:
            return None
        with self._lock:
            store = self._store_for(run.agent_id)
            if store is None:
                return None
            stored = store.merge(lesson)
            self._absorbed += 1
            if str(getattr(stored, "id", "")) != str(lesson.id):
                self._merged += 1
            self._persist()
            return stored

    def observe(self, run: TrainingRun) -> Optional[Dict[str, Any]]:
        """run → genome observation (the agent's self-assessment vs the gate)."""
        if not self.genome_enabled:
            return None
        genome = self._genome_obj()
        if genome is None:
            return None
        floor = float(run.detail.get("min_score", GRADUATION_MIN_SCORE))
        claimed = "yes" if float(run.training_score) >= floor else "no"
        truth = "yes" if run.certified else "no"
        try:
            genome.observe(run.agent_id, claimed, truth)
        except Exception:
            return None
        return {
            "agent_id": str(run.agent_id),
            "claimed": claimed,
            "truth": truth,
            "agreement": claimed == truth,
        }

    def evolve(self) -> List[Dict[str, Any]]:
        """Apply the genome's own advice, mutating the probationary agents.

        Only ``retrain`` mutates.  A mutation resets the agent's observations, so
        it falls straight back to ``observe`` and cannot be mutated again until
        fresh evidence arrives — evolution cannot thrash.
        """
        if not self.genome_enabled:
            return []
        genome = self._genome_obj()
        if genome is None:
            return []
        try:
            rows = list(genome.rank())
        except Exception:
            # A genome that cannot even be listed must not take the pass down
            # (``fitness`` guards the same call — keep the two consistent).
            return []
        actions: List[Dict[str, Any]] = []
        with self._lock:
            for row in rows:
                agent_id = str(row.get("agent_id", ""))
                if not agent_id:
                    continue
                try:
                    advice = genome.advise(agent_id)
                except Exception:
                    # A genome whose advice cannot be read must not take the pass
                    # down (``fitness`` guards the same call — keep them consistent).
                    advice = {}
                action = str(advice.get("action", "keep"))
                mutated = False
                if action == "retrain":
                    try:
                        genome.mutate(agent_id, note="auto-retrain: probation fitness")
                        mutated = True
                        self._mutations.append(agent_id)
                    except Exception:
                        mutated = False
                actions.append({
                    "agent_id": agent_id,
                    "action": action,
                    "mutated": mutated,
                    "fitness": float(advice.get("fitness", 0.0)),
                    "observations": int(advice.get("observations", 0)),
                    "reason": str(advice.get("reason", "")),
                })
            if len(self._mutations) > _MAX_LIMIT:
                del self._mutations[:len(self._mutations) - _MAX_LIMIT]
        return actions

    def fitness(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Per-agent genome standings, best fitness first.

        Each row carries the evidence behind the number (observations,
        agreements, dissents, streak) plus the genome's own next action, so a
        dashboard can show *why* an agent would be re-trained instead of just a
        score.
        """
        if not self.genome_enabled:
            return []
        genome = self._genome_obj()
        if genome is None:
            return []
        try:
            rows = genome.rank(include_retired=True)
        except Exception:
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            agent_id = str(row.get("agent_id", ""))
            if not agent_id:
                continue
            try:
                advice = genome.advise(agent_id)
            except Exception:
                advice = {}
            out.append({
                "agent_id": agent_id,
                "fitness": float(row.get("fitness", _NEUTRAL_FITNESS)),
                "status": str(row.get("status", "")),
                "observations": int(row.get("observations", 0)),
                "agreements": int(row.get("agreements", 0)),
                "dissent": int(row.get("dissent", 0)),
                "streak": int(row.get("streak", 0)),
                "best_streak": int(row.get("best_streak", 0)),
                "generation": int(row.get("generation", 1)),
                "retired": bool(row.get("retired", False)),
                "action": str(advice.get("action", "")),
                "reason": str(advice.get("reason", "")),
            })
        return out[:_clamp_limit(limit)]

    def tick(self, run: TrainingRun) -> Dict[str, Any]:
        """Run the whole loop for one run and return its report."""
        lesson = self.absorb(run)
        observation = self.observe(run)
        actions = self.evolve()
        report: Dict[str, Any] = {
            "agent_id": str(run.agent_id),
            "run_id": str(run.run_id),
            "verdict": str(run.verdict),
            "lesson": _lesson_view(lesson),
            "genome": observation,
            "evolved": [a for a in actions if a["action"] != "keep"],
            "mutated": [a["agent_id"] for a in actions if a["mutated"]],
        }
        with self._lock:
            self._ticks += 1
            self._last_tick = report
        return report

    # ── views ────────────────────────────────────────────────────────────
    def lessons(self, agent_id: Optional[str] = None,
                limit: int = 50) -> List[Any]:
        """Stored lessons (optionally for one agent), most confident first."""
        bounded = _clamp_limit(limit)
        with self._lock:
            if agent_id is not None:
                store = self._stores.get(str(agent_id))
                items = list(store.all()) if store is not None else []
            else:
                items = [lesson for store in self._stores.values()
                         for lesson in store.all()]
        items.sort(key=lambda item: (-float(item.confidence),
                                     -float(item.created_at), str(item.id)))
        return items[:bounded]

    def stats(self) -> Dict[str, Any]:
        """Counters for the dashboard and health surfaces."""
        with self._lock:
            genome = self._genome_obj()
            lesson_count = sum(len(store.all()) for store in self._stores.values())
            return {
                "genome_enabled": bool(self.genome_enabled),
                "ticks": self._ticks,
                "absorbed": self._absorbed,
                "merged": self._merged,
                "agents_with_lessons": len(self._stores),
                "lessons": lesson_count,
                "mutations": len(self._mutations),
                "database": (
                    str(self._lesson_db_path) if self._database is not None else None
                ),
                "genome": self._genome_stats(genome),
                "last_tick": self._last_tick,
            }

    def _genome_stats(self, genome: Any) -> Optional[Dict[str, Any]]:
        """The genome's own counters, or ``{}`` when it cannot answer.

        The dashboard polls this route; a genome that is missing or broken must
        render an empty panel, never a 500.
        """
        if genome is None:
            return None
        try:
            return dict(genome.stats())
        except Exception:
            return {}

    def last_tick(self) -> Optional[Dict[str, Any]]:
        """The most recent tick report, or ``None``."""
        return self._last_tick

    def reset(self) -> None:
        """Forget every lesson and counter (tests/ops)."""
        with self._lock:
            self._stores.clear()
            self._absorbed = 0
            self._merged = 0
            self._mutations = []
            self._ticks = 0
            self._last_tick = None

    def close(self) -> None:
        """Release the lesson database handle (idempotent, never raises).

        The loop owns exactly one connection for its whole life, so a service
        that drops the loop (restart, tests) must hand the handle back instead
        of leaking a file descriptor until garbage collection.
        """
        with self._lock:
            database = self._database
            self._database = None
        if database is not None:
            try:
                database.close()
            except Exception:
                pass

    # ── persistence ──────────────────────────────────────────────────────
    def _persist(self) -> None:
        """Upsert every in-memory lesson into the database (no-op without one)."""
        if self._database is None:
            return
        lessons = [lesson for store in self._stores.values()
                   for lesson in store.all()]
        try:
            self._database.save(lessons)
        except Exception:  # pragma: no cover - a broken DB must not break a run
            return


_FIELD: Optional[FieldLoop] = None
_FIELD_LOCK = threading.Lock()


def get_field_loop(**kwargs: Any) -> FieldLoop:
    """Process-wide field loop (tests pass ``lesson_db=`` / ``genome=``)."""
    global _FIELD
    if kwargs:
        return FieldLoop(**kwargs)
    with _FIELD_LOCK:
        if _FIELD is None:
            _FIELD = FieldLoop(lesson_db=default_lesson_db_path())
        return _FIELD


def reset_field_loop() -> None:
    """Drop the cached singleton, releasing its database handle (tests only)."""
    global _FIELD
    with _FIELD_LOCK:
        previous = _FIELD
        _FIELD = None
    if previous is not None:
        previous.close()
