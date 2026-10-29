"""Agent Genome (v2.2) — agents that evolve.

Each agent has a permanent "genome" row: persona, lineage (generation / parent),
and lifetime performance (runs, successes, latency, verdict alignment).  The
Genome manager turns real outcomes into updated standings, promotes the strong
and re-trains the weak, and keeps an append-only timeline so the UI can show how
an agent evolved.

**Two backends, one class (P3).**  The canonical genome is
:class:`~src.novamind.genome_v2.GenomeV2` persisted by
:mod:`src.novamind.genome_store` (JSON) — that is what the Academy, the training
field loop and the council actually read.  Passing a ``GenomeV2`` here makes
every method below delegate to :class:`~.adapter.GenomeV2Adapter`, so the legacy
API writes the **same row in the same store** instead of a second SQLite copy.
Passing a ``SessionStore`` keeps the pre-P3 SQLite behaviour byte-for-byte
(legacy callers and their tests are untouched, the data is imported once by
:mod:`src.novamind.genome_migrate`).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .scoring import classify, compute_standing

__all__ = ["Genome"]

# Fallback personas for the five council roles (mirrors council.COUNCIL_MEMBERS
# without importing it — the genome must be usable on its own).
DEFAULT_PERSONAS: Dict[str, str] = {
    "analyst": "المُحلِّل: يزن الأرقام والأدلة والمنطق قبل أي رأي.",
    "critic": "الناقد: يكشف المخاطر والثغرات وأسوأ السيناريوهات بلا مجاملة.",
    "visionary": "صاحب الرؤية: ينظر إلى المدى البعيد والفرص الطموحة بجرأة.",
    "pragmatist": "العملي: يفكّر بالتكلفة والوقت والحدّ الأدنى القابل للتنفيذ.",
    "expert": "الخبير: يستدعي المعرفة المتخصّصة وأفضل الممارسات والدروس.",
}
DEFAULT_NAMES: Dict[str, str] = {
    "analyst": "المُحلِّل",
    "critic": "الناقد",
    "visionary": "صاحب الرؤية",
    "pragmatist": "العملي",
    "expert": "الخبير",
}


class Genome:
    """High-level operations over a genome store (v2 JSON, or legacy SQLite)."""

    def __init__(self, store: Any) -> None:
        self.store = store
        # A GenomeV2 (or an adapter already wrapping one) means: one store only.
        self._adapter: Optional[Any] = None
        adapter_cls = _adapter_class()
        if adapter_cls is not None:
            if isinstance(store, adapter_cls):
                self._adapter = store
            else:
                try:
                    from ..genome_v2 import GenomeV2

                    if isinstance(store, GenomeV2):
                        self._adapter = adapter_cls(store)
                except Exception:  # pragma: no cover - genome_v2 is always here
                    self._adapter = None

    @property
    def is_genome_v2(self) -> bool:
        """True when this instance writes the canonical v2 store."""
        return self._adapter is not None

    @classmethod
    def from_genome_v2(cls, genome: Any = None,
                       *, seed: bool = True) -> "Genome":
        """Build a Genome over the process-wide v2 store (the production path)."""
        from ..genome_v2 import get_genome_v2

        instance = cls(genome if genome is not None else get_genome_v2())
        if seed:
            instance.seed()
        return instance

    # ── seeding ──────────────────────────────────────────────────────────
    def seed(self, members: Optional[List[Any]] = None,
             personas: Optional[Dict[str, str]] = None,
             names: Optional[Dict[str, str]] = None) -> int:
        """Ensure a genome row exists for every member. Returns rows created.

        ``members`` may be council member objects (with ``id``/``name``/``system``)
        or plain ids.  Existing rows are left untouched so the seed is idempotent.
        """

        if self._adapter is not None:
            return self._adapter.seed(members, personas, names)
        personas = personas if personas is not None else DEFAULT_PERSONAS
        names = names if names is not None else DEFAULT_NAMES
        created = 0
        for m in members if members is not None else list(DEFAULT_PERSONAS):
            agent_id = getattr(m, "id", None) or str(m)
            name = getattr(m, "name", None) or names.get(agent_id, agent_id)
            persona = getattr(m, "system", None) or personas.get(agent_id, "")
            emoji = getattr(m, "emoji", None)
            existing = self.store.get_agent(agent_id)
            if existing is None:
                self.store.upsert_agent(agent_id, name=name, persona=persona,
                                        meta={"emoji": emoji} if emoji else None)
                created += 1
            elif emoji and not (existing.get("meta") or {}).get("emoji"):
                self.store.update_agent(
                    agent_id, meta={**(existing.get("meta") or {}), "emoji": emoji})
        return created

    # ── learning ─────────────────────────────────────────────────────────
    def record(self, agent_id: str, *, success: bool, latency_ms: int = 0,
               consensus: Optional[float] = None, kind: str = "outcome",
               detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Fold one real outcome into an agent's genome; return the new row."""

        if self._adapter is not None:
            return self._adapter.record(agent_id, success=success, latency_ms=latency_ms, consensus=consensus, kind=kind, detail=detail)
        cur = self.store.get_agent(agent_id)
        if cur is None:
            cur = self.store.upsert_agent(
                agent_id, name=DEFAULT_NAMES.get(agent_id, agent_id),
                persona=DEFAULT_PERSONAS.get(agent_id, ""),
            )
        runs = int(cur["runs"]) + 1
        successes = int(cur["successes"]) + (1 if success else 0)
        latency_sum = int(cur["latency_sum_ms"]) + int(latency_ms or 0)
        consensus_sum = float(cur["consensus_sum"]) + float(consensus or 0.0)
        consensus_n = int(cur["consensus_n"]) + (1 if consensus is not None else 0)
        standing = compute_standing(runs, successes, consensus_sum, consensus_n,
                                    latency_sum, prior=float(cur["standing"]))
        return self.store.record_agent_outcome(
            agent_id, success=success, latency_ms=latency_ms, consensus=consensus,
            standing=standing, status=classify(standing), kind=kind, detail=detail,
        )

    def outcome_from_influence(self, agent_id: str, alignment: float,
                               standing_delta: int, consensus: float,
                               latency_ms: int = 0,
                               detail: Optional[Dict[str, Any]] = None
                               ) -> Dict[str, Any]:
        """Record a council member's result from its verdict alignment."""

        if self._adapter is not None:
            return self._adapter.outcome_from_influence(agent_id, alignment=alignment, standing_delta=standing_delta, consensus=consensus, latency_ms=latency_ms, detail=detail)
        return self.record(
            agent_id, success=standing_delta > 0, latency_ms=latency_ms,
            consensus=consensus, kind="council",
            detail={**(detail or {}), "alignment": round(float(alignment), 4),
                    "standing_delta": int(standing_delta)},
        )

    # ── lifecycle ────────────────────────────────────────────────────────
    def reset(self, agent_id: str, note: str = "") -> Optional[Dict[str, Any]]:
        """Re-train an agent: zero its stats, bump generation, keep lineage."""

        if self._adapter is not None:
            return self._adapter.reset(agent_id, note=note)
        return self.store.reset_agent(agent_id, note=note)

    # ── views / portability ──────────────────────────────────────────────
    def rank(self) -> List[Dict[str, Any]]:
        """Every agent, best standing first."""

        if self._adapter is not None:
            return self._adapter.rank()
        return self.store.list_agents()

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """One row (v2 mode) / ``SessionStore.get_agent`` (legacy mode)."""
        if self._adapter is not None:
            return self._adapter.get_agent(agent_id)
        return self.store.get_agent(agent_id)

    def list_agents(self) -> List[Dict[str, Any]]:
        """Every row, best first (both modes)."""
        if self._adapter is not None:
            return self._adapter.list_agents()
        return self.store.list_agents()

    def update_agent(self, agent_id: str, name: Optional[str] = None,
                     persona: Optional[str] = None,
                     meta: Optional[Dict[str, Any]] = None) -> bool:
        """Rename/re-persona a row (both modes)."""
        if self._adapter is not None:
            return self._adapter.update_agent(agent_id, name=name,
                                              persona=persona, meta=meta)
        return bool(self.store.update_agent(agent_id, name=name,
                                            persona=persona, meta=meta))

    def fitness_of(self, agent_id: str) -> float:
        """Fitness in [0, 1] for the orchestrator router (both modes)."""
        if self._adapter is not None:
            return self._adapter.fitness_of(agent_id)
        row = self.store.get_agent(agent_id) or {}
        try:
            return float(row.get("standing", 0.5))
        except (TypeError, ValueError):
            return 0.5

    def detail(self, agent_id: str, timeline_limit: int = 100
               ) -> Optional[Dict[str, Any]]:
        if self._adapter is not None:
            return self._adapter.detail(agent_id, timeline_limit=timeline_limit)
        agent = self.store.get_agent(agent_id)
        if agent is None:
            return None
        agent = dict(agent)
        agent["timeline"] = self.store.agent_timeline(agent_id, limit=timeline_limit)
        return agent

    def export(self) -> Dict[str, Any]:
        """Whole genome (agents + full timeline) as a JSON-ready dict."""

        if self._adapter is not None:
            return self._adapter.export()
        agents = self.store.list_agents()
        return {
            "version": 1,
            "agents": agents,
            "events": {a["agent_id"]: self.store.agent_timeline(a["agent_id"], limit=10000)
                       for a in agents},
        }

    def import_(self, payload: Dict[str, Any]) -> int:
        """Import agents from an exported genome (idempotent by agent_id)."""

        if self._adapter is not None:
            return self._adapter.import_(payload)
        agents = (payload or {}).get("agents") or []
        return self.store.genome_import(agents)


def _adapter_class() -> Any:
    """The adapter type, imported lazily so this module stays cheap."""
    try:
        from .adapter import GenomeV2Adapter

        return GenomeV2Adapter
    except Exception:  # pragma: no cover - adapter ships with the module
        return None
