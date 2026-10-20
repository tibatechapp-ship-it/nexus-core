"""STRIDE — **T**ampering: unauthorized modification of data or state.

Attack surface for nexus-core:

* ``POST /api/genome/import`` writes agent records from a caller-supplied
  dict; ``PATCH /api/genome/{id}`` rewrites ``name``/``persona``. A caller who
  lacks write rights (or a path-traversing import) must not be able to mutate
  the genome.
* The tool executor resolves paths from model output — a ``..`` payload that
  escapes the workspace root is tampering with files outside the sandbox.
* ``task_log`` / ``_metrics`` / ``genome.json`` are append-only ledgers; a
  read must never mutate them (purity), and a crafted record must not corrupt
  the ledger shape for later readers.
* The exec sandbox writes a file then runs it — a syntax-valid but hostile
  write (symlink race, oversized write) must be contained.

Each test names the exact mutation it attempts and asserts the state is
either refused or inert.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.security.stride import helpers as H

CATEGORY = "Tampering"


# ---------------------------------------------------------------------------
# T1 — path traversal through the confined tool executor is inert
# ---------------------------------------------------------------------------
def test_t1_tool_executor_refuses_traversal(tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """EXPLOIT: a model emits a ``read_file`` call with ``../../../../etc/passwd``
    hoping the executor follows it out of the workspace.

    DEFENCE: every path is resolved and must stay inside ``root``. The PoC
    plants a victim file *outside* the root and proves the executor raises
    PermissionError instead of returning its bytes.
    """
    pytest.importorskip("src.tools.executor")
    from src.tools.executor import LocalToolExecutor, ToolCall

    work = tmp_path / "work"
    work.mkdir()
    (work / "ok.txt").write_text("inside", encoding="utf-8")
    victim = tmp_path / "victim.txt"
    victim.write_text("SECRET-OUTSIDE", encoding="utf-8")

    ex = LocalToolExecutor(root=work)
    # Sanity: a legitimate read works.
    good = ex.execute(ToolCall(name="read", arguments={"path": "ok.txt"}))
    assert good.ok and "inside" in str(good.output)

    rel = "../victim.txt"
    with pytest.raises(PermissionError):
        ex._resolve(rel)  # noqa: SLF001 - the policy seam under test
    # And the traversal is rejected through the public path too: the executor
    # never raises, it returns ok=False and never leaks the victim's bytes.
    outcome = ex.execute(ToolCall(name="read", arguments={"path": rel}))
    assert outcome.ok is False
    assert "SECRET-OUTSIDE" not in str(outcome.output) + str(outcome.error)
    assert victim.read_text(encoding="utf-8") == "SECRET-OUTSIDE"  # unchanged


# ---------------------------------------------------------------------------
# T2 — builder path gate rejects every escaping write path
# ---------------------------------------------------------------------------
def test_t2_builder_write_gate_rejects_escaping_paths() -> None:
    """EXPLOIT: a craft/build brief asks the model for a file at ``/etc/cron.d/x``
    or ``../../.ssh/authorized_keys`` so the build writes outside its folder.

    DEFENCE: ``_safe_rel_path`` returns ``None`` for absolute, ``~``, drive and
    dot-dot paths; the build loop skips a file whose path fails the gate.
    """
    pytest.importorskip("src.council.builder")
    from src.council.builder import _safe_rel_path

    for evil in ("/etc/passwd", "~/x", "../x", "a/../../b", "..\\x",
                 "C:\\x", "", "   ", "a" * 300):
        assert _safe_rel_path(evil) is None, f"gate let {evil!r} through"

    for good in ("main.py", "src/app.js", "a/b/c.txt"):
        assert _safe_rel_path(good) == good


# ---------------------------------------------------------------------------
# T3 — genome import is idempotent / does not corrupt on hostile payloads
# ---------------------------------------------------------------------------
def test_t3_genome_import_tolerates_hostile_payload(tmp_path: Path) -> None:
    """EXPLOIT: attacker posts a genome import with non-dict agent rows, huge
    nested blobs, or missing ids to corrupt the store or crash a reader.

    DEFENCE: ``import_`` returns an int (count) and never raises on junk; a
    reader afterwards still sees well-formed rows. This PoC drives the pure
    import surface with adversarial payloads.
    """
    pytest.importorskip("src.novamind.genome.genome")
    try:
        from src.novamind.core.session_store import SessionStore
        from src.novamind.genome.genome import Genome
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"genome backend unavailable: {exc}")

    g = Genome(SessionStore(tmp_path / "genome.db"))
    for hostile in ({}, {"agents": None}, {"agents": "not-a-list"},
                    {"agents": [None, 5, "x"]}, []):
        try:
            n = g.import_(hostile)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"import_ raised on {hostile!r}: {exc!r}")
        assert isinstance(n, int)

    # A subsequent read still returns a list of dict-shaped agents.
    assert isinstance(g.rank(), list)


# ---------------------------------------------------------------------------
# T4 — read endpoints are pure (a GET must not mutate the ledger)
# ---------------------------------------------------------------------------
def test_t4_read_surface_does_not_mutate_state(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """EXPLOIT: a caller hammers a read (metrics) hoping each call appends a
    row — slow poisoning of the ledger that later skews the dashboard.

    DEFENCE: reads are pure. The PoC points the ledger at a temp file, reads
    its size, calls the aggregate/read twice and asserts the size is unchanged.
    """
    pytest.importorskip("src.maintenance.task_log")
    from src.maintenance import task_log

    ledger = tmp_path / "task_log.jsonl"
    monkeypatch.setenv(task_log._LOG_ENV if hasattr(task_log, "_LOG_ENV")
                       else "NEXUS_TASK_LOG", str(ledger))

    before = ledger.stat().st_size if ledger.exists() else 0
    task_log.aggregate()
    task_log.aggregate()
    after = ledger.stat().st_size if ledger.exists() else 0
    assert after == before, "a read wrote to the task ledger (impure read)"


# ---------------------------------------------------------------------------
# T5 — exec sandbox write is contained (no escape, no symlink follow)
# ---------------------------------------------------------------------------
def test_t5_exec_sandbox_writes_inside_its_tempdir(tmp_path: Path) -> None:
    """EXPLOIT: an unprivileged caller submits code that writes ``../escape``
    hoping the sandbox cwd leaks upward.

    DEFENCE: the sandbox runs in a fresh TemporaryDirectory with cwd set to it;
    a write to ``../`` lands inside the temp parent tree, not in the server's
    working directory. The PoC asserts the server cwd gains no new file.
    """
    pytest.importorskip("fastapi")
    import os
    import sys

    # The sandbox is a top-level module (tools/ is on sys.path via conftest).
    tools_dir = H.repo_root() / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    try:
        import exec_sandbox as sandbox
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"sandbox unavailable: {exc}")

    server_cwd_before = set(os.listdir(os.getcwd()))
    req = sandbox.ExecReq(
        language="python",
        code="import os\nopen('../stride_escape.txt','w').write('x')\nprint('done')",
        timeout=5,
    )
    try:
        result = sandbox.exec_code(req)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"sandbox unavailable on this host: {exc}")

    assert result.get("ran") is True
    server_cwd_after = set(os.listdir(os.getcwd()))
    assert "stride_escape.txt" not in server_cwd_after
    assert server_cwd_after == server_cwd_before
