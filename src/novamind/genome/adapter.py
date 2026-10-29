"""One genome, one store — the v1 API served by the v2 genome.

Why this file exists
--------------------
Two genome layers used to exist side by side and **both** were written by a
single council session:

* *v1* — :class:`src.novamind.genome.genome.Genome` over the SQLite
  ``agent_genome`` table (runs / successes / latency / standing);
* *v2* — :class:`src.novamind.genome_v2.GenomeV2` persisted as JSON by
  :mod:`src.novamind.genome_store`, which is what the Academy UI, the training
  field loop and ``/api/maintenance/metrics`` actually read.

The P3 decision (``docs/GENOME_UNIFICATION.md``) is that **v2 is the single
source of truth**.  This adapter is the whole bridge: it implements the v1
surface (``seed`` / ``record`` / ``outcome_from_influence`` / ``reset`` /
``rank`` / ``detail`` / ``export`` / ``import_`` plus the small helpers the HTTP
layer needs) directly on top of a :class:`GenomeV2` instance, so every caller
that used to book-keep in SQLite now book-keeps in the one JSON store.

Two consequences worth stating explicitly:

* ``rank()`` returns the v1 *shape* (``agent_id/name/persona/runs/successes/
  failures/standing/status/timeline``) so ``/api/genome*`` and the UI keep
  working, but the numbers come from v2's fitness (0..1, same scale as v1's
  standing).  v2-only fields (``fitness``, ``observations``,
  ``task_observations``, ``generation``) ride along untouched.
* Display identity (name / persona / emoji) is **derived**, never stored twice:
  a ``meta`` key is written on the v2 row only when someone overrides it
  through the API, and ``GenomeV2.to_dict``/``from_dict`` already round-trip it.

The module is I/O-free (persistence stays in ``genome_store``) and never
imports the council or the agent suite at module import time.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from ..genome_v2 import GenomeV2, _notify, classify_fitness, evidence

__all__ = ["GenomeV2Adapter"]

_STATUS_BLEND = {
    # v2 status → v1 lifecycle bucket (both vocabularies stay readable).
    "elite": "promoted",
    "stable": "active",
    "probationary": "probation",
}


class GenomeV2Adapter:
    """The legacy ``Genome`` API, backed by the one v2 store."""

    #: Marker the council engine uses to skip the now-redundant judge mirror.
    is_genome_v2 = True

    def __init__(self, genome: Optional[GenomeV2] = None) -> None:
        self.genome = genome if genome is not None else GenomeV2()

    # ── identity (derived, never a second store) ─────────────────────────
    def _identity(self, agent_id: str) -> Dict[str, str]:
        """Name / persona / emoji for ``agent_id`` from the live rosters."""
        from .genome import DEFAULT_NAMES, DEFAULT_PERSONAS

        name = DEFAULT_NAMES.get(agent_id, "")
        persona = DEFAULT_PERSONAS.get(agent_id, "")
        emoji = ""
        try:  # council roster wins over the fallback dicts
            from ..council.council import COUNCIL_MEMBERS

            for member in COUNCIL_MEMBERS:
                if member.id == agent_id:
                    name = member.name or name
                    persona = member.system or persona
                    emoji = getattr(member, "emoji", "") or ""
                    break
        except Exception:  # pragma: no cover - council is optional
            pass
        if not name or not persona:
            try:  # the 20-agent suite carries a human title
                from src.agents.manifest import get_manifest

                manifest = get_manifest(agent_id)
                title = getattr(manifest, "title", "") if manifest else ""
                name = name or str(title or "")
            except Exception:  # pragma: no cover - framework is optional
                pass
        return {"name": name or agent_id, "persona": persona, "emoji": emoji}

    def _with_identity(self, row: Mapping[str, Any],
                       limit: Optional[int] = None) -> Dict[str, Any]:
        """A v1-shaped view of one v2 row."""
        out = dict(row)
        agent_id = str(out.get("agent_id", ""))
        overrides = dict(out.get("meta") or {})
        derived = self._identity(agent_id)
        out["name"] = overrides.get("name") or derived["name"]
        out["persona"] = overrides.get("persona") or derived["persona"]
        emoji = overrides.get("emoji") or derived["emoji"]
        if emoji:
            out["emoji"] = emoji

        task_obs = int(out.get("task_observations", 0) or 0)
        task_ok = int(out.get("task_successes", 0) or 0)
        out["runs"] = evidence(out)
        out["successes"] = int(out.get("agreements", 0) or 0) + task_ok
        out["failures"] = max(0, out["runs"] - out["successes"])
        out["standing"] = round(float(out.get("fitness", 0.5)), 4)
        out["status"] = _STATUS_BLEND.get(str(out.get("status")), "active")
        latency = out.get("task_duration_avg")
        out["latency_avg_ms"] = int(round(float(latency) * 1000)) if latency else 0
        out["task_runs"] = task_obs
        history = out.get("history")
        out["timeline"] = list(history or [])
        if limit is not None:
            out["timeline"] = out["timeline"][-int(limit):]
        return out

    # ── seeding ──────────────────────────────────────────────────────────
    def seed(self, members: Optional[Iterable[Any]] = None,
             personas: Optional[Mapping[str, str]] = None,
             names: Optional[Mapping[str, str]] = None) -> int:
        """Ensure a row per member; returns how many were created."""
        from .genome import DEFAULT_NAMES, DEFAULT_PERSONAS

        created = 0
        roster = list(members) if members is not None else sorted(DEFAULT_PERSONAS)
        for member in roster:
            agent_id = str(getattr(member, "id", None) or member)
            if not agent_id:
                continue
            existed = self.genome.snapshot(agent_id) is not None
            row = self.genome.ensure(agent_id)
            if not existed:
                created += 1
            name = (getattr(member, "name", None)
                    or (names or DEFAULT_NAMES).get(agent_id) or "")
            persona = (getattr(member, "system", None)
                       or (personas or DEFAULT_PERSONAS).get(agent_id) or "")
            emoji = getattr(member, "emoji", "") or ""
            meta = dict(row.get("meta") or {})
            if name:
                meta.setdefault("name", str(name))
            if persona:
                meta.setdefault("persona", str(persona))
            if emoji:
                meta.setdefault("emoji", str(emoji))
            if meta:
                row["meta"] = meta
        if created:
            _notify(self.genome)
        return created

    # ── learning ─────────────────────────────────────────────────────────
    def record(self, agent_id: str, *, success: bool, latency_ms: int = 0,
               consensus: Optional[float] = None, kind: str = "outcome",
               detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Fold one task outcome into the v2 row (its task channel)."""
        quality = None
        if detail:
            raw = detail.get("quality")
            try:
                quality = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                quality = None
        row = self.genome.observe_outcome(
            str(agent_id), bool(success),
            duration=max(0.0, float(latency_ms or 0) / 1000.0),
            task=str((detail or {}).get("task", "") or kind)[:200],
            quality=quality,
        )
        return self._with_identity(row)

    def outcome_from_influence(self, agent_id: str, alignment: float,
                               standing_delta: int, consensus: float,
                               latency_ms: int = 0,
                               detail: Optional[Dict[str, Any]] = None
                               ) -> Dict[str, Any]:
        """Fold one council judgement into the v2 judgement channel.

        v1 kept a running ``standing_delta``; v2 models the same evidence as a
        stance against the session's final verdict, so a positive delta is an
        agreement and a non-positive one is a dissent.
        """
        stance = "approve" if float(standing_delta) > 0 else "reject"
        row = self.genome.observe(str(agent_id), stance, "approve")
        if latency_ms:
            row["last_latency_ms"] = int(latency_ms)
        return self._with_identity(row)

    # ── lifecycle ────────────────────────────────────────────────────────
    def reset(self, agent_id: str, note: str = "") -> Optional[Dict[str, Any]]:
        """Re-train: bump the generation, zero the evidence, keep the lineage."""
        if self.genome.snapshot(agent_id) is None:
            return None
        return self._with_identity(self.genome.mutate(agent_id, note=note))

    # ── views / portability ──────────────────────────────────────────────
    def rank(self) -> List[Dict[str, Any]]:
        """Every non-retired agent, best fitness first (v1 row shape)."""
        return [self._with_identity(row) for row in self.genome.rank()]

    def list_agents(self) -> List[Dict[str, Any]]:
        """Alias of :meth:`rank` (``SessionStore.list_agents`` spelling)."""
        return self.rank()

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        row = self.genome.snapshot(agent_id)
        return self._with_identity(row) if row is not None else None

    def update_agent(self, agent_id: str, name: Optional[str] = None,
                     persona: Optional[str] = None, meta: Optional[Mapping[str, Any]] = None
                     ) -> bool:
        """Rename/re-persona a row through the API (stored on the v2 row)."""
        row = self.genome.snapshot(agent_id)
        if row is None:
            return False
        live = self.genome.ensure(agent_id)
        current = dict(live.get("meta") or {})
        if name is not None:
            current["name"] = str(name)
        if persona is not None:
            current["persona"] = str(persona)
        if meta:
            current.update({str(k): v for k, v in meta.items()})
        live["meta"] = current
        _notify(self.genome)
        return True

    def detail(self, agent_id: str, timeline_limit: int = 100
               ) -> Optional[Dict[str, Any]]:
        row = self.genome.snapshot(agent_id)
        if row is None:
            return None
        out = self._with_identity(row, limit=timeline_limit)
        out["advice"] = self.genome.advise(agent_id)
        return out

    def fitness_of(self, agent_id: str) -> float:
        """Fitness for the orchestrator router (same contract as its FakeGenome)."""
        row = self.genome.snapshot(agent_id)
        return float(row["fitness"]) if row else 0.5

    def export(self) -> Dict[str, Any]:
        """Whole genome in the v1 export shape (agents + per-agent timelines)."""
        agents = self.rank()
        return {
            "version": 2,
            "agents": agents,
            "events": {a["agent_id"]: list(a.get("timeline") or []) for a in agents},
        }

    def import_(self, payload: Mapping[str, Any]) -> int:
        """Import a v1/v2 export; idempotent per ``agent_id``.

        A v1 row carries only aggregates (runs/successes/standing), so they are
        folded into v2's **task** channel: ``task_observations=runs``,
        ``task_successes=successes``, ``task_ewma=success rate``.  Existing
        rows are never lowered — an import can only add evidence.
        """
        imported = 0
        rows: Any = (payload or {}).get("agents") or []
        if isinstance(rows, Mapping):
            # A v2 ``to_dict`` payload nests the agent table one level deeper.
            nested = rows.get("agents")
            rows = list(nested.values()) if isinstance(nested, Mapping) else list(rows.values())
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            agent_id = str(row.get("agent_id") or "").strip()
            if not agent_id:
                continue
            runs = int(row.get("runs", 0) or 0)
            successes = int(row.get("successes", 0) or 0)
            standing = row.get("standing")
            standing_value: Optional[float] = None
            if standing is not None:
                try:
                    standing_value = max(0.0, min(1.0, float(standing)))
                except (TypeError, ValueError):
                    standing_value = None
            live = self.genome.ensure(agent_id)
            if runs > 0:
                live["task_observations"] = max(int(live.get("task_observations", 0) or 0), runs)
                live["task_successes"] = max(int(live.get("task_successes", 0) or 0), successes)
                # v1 ``standing`` is the authoritative blended score (success,
                # consensus, speed); it is the best single anchor for the v2
                # task EWMA.  Without it, fall back to the raw success rate.
                anchor = standing_value if standing_value is not None else (
                    successes / runs if runs else 0.5)
                live["task_ewma"] = round(max(0.0, min(1.0, anchor)), 4)
            # A standing with no runs carries no evidence (v1 only moves it
            # when a run lands), so there is nothing to fold: identity stays,
            # and fitness keeps its neutral prior.
            # ``import_`` above writes the fields directly, so the cached
            # fitness/status have to be rebuilt from them (v2 only recomputes
            # inside observe*).
            live["fitness"] = self.genome._blended_fitness(live)
            live["status"] = classify_fitness(float(live["fitness"]))
            name = str(row.get("name") or "")
            persona = str(row.get("persona") or "")
            if name or persona:
                meta = dict(live.get("meta") or {})
                if name:
                    meta.setdefault("name", name)
                if persona:
                    meta.setdefault("persona", persona)
                live["meta"] = meta
            imported += 1
        if imported:
            _notify(self.genome)
        return imported
