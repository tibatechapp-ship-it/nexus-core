# Genome stores — why there are two, and how they relate

nexus-core ships **two genome implementations**. They are not duplicates by
accident; they score different things and are surfaced by different routes. This
note makes the split explicit so future work does not unify them by mistake.

## v1 — the council genome (SQLite)

- Code: `src/novamind/genome/genome.py` (`class Genome`, table `agent_genome`)
  + `src/novamind/genome/scoring.py`.
- Scored by: the flagship **6-member Living Council** (`/api/council/debate`,
  `/api/council/stream`).
- Surfaced by: `GET /api/genome`, `/api/genome/{agent_id}`,
  `/api/genome/export`, `POST /api/genome/import`,
  `POST /api/genome/{agent_id}/reset` (owner: `nexus_agent.py`).
- Persistence: **SQLite** (durable across restarts).
- Meaning: per-member **standing** — who was right across debates; rises and
  falls with outcomes. Powers the 🧬 council genome panel.

## v2 — the fitness genome (JSON)

- Code: `src/novamind/genome_v2.py` (`GenomeV2`) + `src/novamind/genome_store.py`
  (the only disk touch-point).
- Scored by: two channels —
  1. the **workbench council** (3-member, `/api/deliberate`) judgement accuracy
     (claimed stance vs final verdict, EWMA + confidence shrinkage), and
  2. **real task outcomes** — every `/api/chat` call records success/failure and
     latency via `_record_task_outcome` → `observe_outcome`.
- Surfaced by: `GET /api/training/fitness` (per-agent fitness + task stats) and
  the 🎓 Agent Academy panel's *fitness* tab.
- Persistence: **JSON** at `$NEXUS_GENOME_PATH` → `<repo>/data/genome.json`.
- Meaning: per-agent **fitness / traits** used to rank, retire and **mutate**
  agents (the field loop evolves the weak).

## The bridge (v1.20.2)

`/api/council/debate` mirrors each member's stance into the v2 store: the
council is constructed with `judge=_record_council_judgements`, which calls
`genome_v2.observe_council(stances, "approve")` after the debate. So a flagship
debate now moves **both** stores — v1 by design and v2 through the bridge.

Guard rails: `judgement_stances()` is pure and tolerant of junk; the judge runs
inside `try/except`, so a missing/broken bridge never breaks a debate.

## The remaining gap (documented, not fixed)

The two stores are still **separate persistences**:

- `/api/training/fitness` and the Academy panel read **v2 only**. They do not
  show the flagship 6-member council's judgement quality.
- `/api/genome*` reads **v1 only**. It does not show task outcomes or the
  workbench council's accuracy.

The bridge forwards council judgements into v2, but it does **not** unify the
storage — a consumer that wants "the whole picture for agent X" must currently
read both endpoints. Unifying them (one source of truth) is a **design decision
deferred to a future release**, deliberately not taken here: the two stores
serve different UIs with different semantics, and a naive merge would risk the
council panel or the Academy panel silently losing data.
