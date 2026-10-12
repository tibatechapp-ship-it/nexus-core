"""Agent Genome (v2.2) — agents that evolve.

Each agent has a permanent "genome" row: persona, lineage (generation / parent),
and lifetime performance (runs, successes, latency, verdict alignment).  The
Genome manager turns real outcomes into updated standings, promotes the strong
and re-trains the weak, and keeps an append-only timeline so the UI can show how
an agent evolved.

Persistence lives in :class:`~novamind.core.session_store.SessionStore`; this
module is the brain (scoring + lifecycle), so the store stays a dumb database.
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
    """High-level operations over the ``agent_genome`` store."""

    def __init__(self, store: Any) -> None:
        self.store = store

    # ── seeding ──────────────────────────────────────────────────────────
    def seed(self, members: Optional[List[Any]] = None,
             personas: Optional[Dict[str, str]] = None,
             names: Optional[Dict[str, str]] = None) -> int:
        """Ensure a genome row exists for every member. Returns rows created.

        ``members`` may be council member objects (with ``id``/``name``/``system``)
        or plain ids.  Existing rows are left untouched so the seed is idempotent.
        """
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
        return self.record(
            agent_id, success=standing_delta > 0, latency_ms=latency_ms,
            consensus=consensus, kind="council",
            detail={**(detail or {}), "alignment": round(float(alignment), 4),
                    "standing_delta": int(standing_delta)},
        )

    # ── lifecycle ────────────────────────────────────────────────────────
    def reset(self, agent_id: str, note: str = "") -> Optional[Dict[str, Any]]:
        """Re-train an agent: zero its stats, bump generation, keep lineage."""
        return self.store.reset_agent(agent_id, note=note)

    # ── views / portability ──────────────────────────────────────────────
    def rank(self) -> List[Dict[str, Any]]:
        """Every agent, best standing first."""
        return self.store.list_agents()

    def detail(self, agent_id: str, timeline_limit: int = 100
               ) -> Optional[Dict[str, Any]]:
        agent = self.store.get_agent(agent_id)
        if agent is None:
            return None
        agent = dict(agent)
        agent["timeline"] = self.store.agent_timeline(agent_id, limit=timeline_limit)
        return agent

    def export(self) -> Dict[str, Any]:
        """Whole genome (agents + full timeline) as a JSON-ready dict."""
        agents = self.store.list_agents()
        return {
            "version": 1,
            "agents": agents,
            "events": {a["agent_id"]: self.store.agent_timeline(a["agent_id"], limit=10000)
                       for a in agents},
        }

    def import_(self, payload: Dict[str, Any]) -> int:
        """Import agents from an exported genome (idempotent by agent_id)."""
        agents = (payload or {}).get("agents") or []
        return self.store.genome_import(agents)
