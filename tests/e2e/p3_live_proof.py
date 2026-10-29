"""Live end-to-end proof of P3: one genome store behind the whole surface.

Boots the real launcher (``nexus_agent.main``) on a spare port with a throwaway
genome file and a *legacy* ``sessions.db`` that already holds history, then
checks over HTTP that:

1. the v2 store is the one that answers (6 council members seeded),
2. the legacy rows were folded in once, without inflating counters,
3. ``/api/genome`` (v1 shape), ``PATCH /api/genome/{id}`` and
   ``/api/training/agents?roster=1`` all read/write that same store,
4. writing through the v1 API never recreates the legacy table's authority.

Run:  python tests/e2e/p3_live_proof.py
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORT = int(os.environ.get("P3_PROOF_PORT", "8099"))
WORK = Path(os.environ["TMPDIR"]) / "p3-live"
GENOME = WORK / "genome.json"
DB = WORK / "sessions.db"

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + label + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def get(path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=10) as r:
        return json.loads(r.read().decode())


def patch(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="PATCH")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def legacy_rows() -> dict[str, dict]:
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        return {r["agent_id"]: dict(r) for r in conn.execute(
            "SELECT * FROM agent_genome")}


def seed_legacy() -> None:
    """A pre-P3 database: history for two agents nobody seeds any more."""
    sys.path.insert(0, str(ROOT / "src"))
    from novamind.core.session_store import SessionStore  # noqa: PLC0415

    store = SessionStore(DB)
    store.upsert_agent("analyst", "المحلل القديم", persona="legacy")
    for latency in (100, 120, 90):
        store.record_agent_outcome("analyst", True, latency_ms=latency,
                                   standing=0.62)
    store.upsert_agent("retired_agent", "وكيل متقاعد")
    store.record_agent_outcome("retired_agent", False, latency_ms=400,
                               standing=0.11, status="retired")


def wait_ready(proc: subprocess.Popen, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2).read()
            return True
        except (urllib.error.URLError, ConnectionError, socket.timeout):
            time.sleep(1.0)
    return False


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    for leftover in (GENOME, DB):
        leftover.unlink(missing_ok=True)
    seed_legacy()
    before = legacy_rows()
    print(f"seeded legacy db: {sorted(before)}")

    env = dict(os.environ, NEXUS_PORT=str(PORT), NEXUS_GENOME_PATH=str(GENOME),
               NEXUS_DB=str(DB), PYTHONPATH=f"{ROOT}:{ROOT / 'src'}")
    proc = subprocess.Popen([sys.executable, "nexus_agent.py"], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        if not wait_ready(proc):
            out = proc.stdout.read() if proc.stdout else ""
            print(out[-3000:])
            check("server booted", False)
            return 1
        check("server booted on :%d" % PORT, True)

        # ── 1. the v2 store is the source of truth ──────────────────────
        check("v2 genome file created", GENOME.exists(), str(GENOME))
        disk = json.loads(GENOME.read_text())
        disk_ids = {a["agent_id"] if isinstance(a, dict) else a
                    for a in (disk.get("agents") or [])} if isinstance(disk.get("agents"), list) else set(disk.get("agents") or {})
        check("v2 store holds the 6 council members",
              {"tork_acil", "analyst", "critic", "visionary", "pragmatist",
               "expert"} <= disk_ids, ",".join(sorted(disk_ids))[:120])

        # ── 2. legacy history folded in, counters not inflated ──────────
        genome = get("/api/genome")
        agents = {a["agent_id"]: a for a in genome.get("agents", [])}
        check("/api/genome returns the v1 shape",
              set(genome) >= {"agents"}, ",".join(sorted(genome))[:120])
        check("legacy-only agent survived the import",
              "retired_agent" in agents)
        analyst = agents.get("analyst", {})
        obs = analyst.get("observations") or analyst.get("total") or 0
        check("imported history kept exactly (3 outcomes, not 6)", obs == 3,
              f"observations={obs}")

        # ── 3. the training roster reads the same store ─────────────────
        roster = get("/api/training/agents?roster=1")
        roster_ids = {a.get("agent_id") or a.get("id") for a in roster.get("agents", [])}
        check("?roster=1 lists the council",
              {"tork_acil", "analyst", "critic", "visionary", "pragmatist",
               "expert"} <= roster_ids, f"{len(roster_ids)} ids")

        # ── 4. a write through the v1 API lands in v2 only ──────────────
        patch("/api/genome/critic", {"note": "p3-live-proof"})
        after_disk = json.loads(GENOME.read_text())
        blob = json.dumps(after_disk)
        check("v1 PATCH persisted into the v2 file", "p3-live-proof" in blob)
        after = legacy_rows()
        check("legacy table untouched by post-import writes",
              after.get("analyst", {}).get("updated_at")
              == before["analyst"]["updated_at"],
              f"{after['analyst']['updated_at']} == {before['analyst']['updated_at']}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()

    print()
    if failures:
        print(f"FAILED {len(failures)}: " + ", ".join(failures))
        return 1
    print("ALL LIVE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
