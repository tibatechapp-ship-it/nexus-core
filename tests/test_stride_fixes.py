"""Regression guards for the STRIDE security-audit fixes.

These live in the normal suite (not ``tests/security/stride/``) so the fix stays
covered by the standard gate, independent of the PoC framework:

* **I4** — the confined tool executor must refuse in-root credential stores.
* **T3/D2** — ``genome_import`` must tolerate a hostile payload instead of
  raising (which produced an HTTP 500 on ``POST /api/genome/import``).
* **I1** — ``/api/diag`` must not disclose absolute server paths.
"""
from __future__ import annotations

import json

import pytest

from src.tools.executor import LocalToolExecutor, ToolCall, is_sensitive_file


# ---------------------------------------------------------------------------
# I4 — credential deny-list (SH-01)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path",
    [".env", ".env.local", ".env.bak", "id_rsa", "id_ed25519", "cert.pem",
     "server.key", "secrets.json", "credentials.json", "client.p12",
     ".git-credentials", ".netrc"],
)
def test_i4_executor_refuses_credential_stores(tmp_path, path):
    ex = LocalToolExecutor(root=tmp_path)
    out = ex.execute(ToolCall(name="read", arguments={"path": path}))
    assert not out.ok, f"executor read the credential store {path!r}"
    assert "refused" in (out.error or "").lower()


def test_i4_executor_still_reads_documentation(tmp_path):
    """``.env.example`` documents variable NAMES — it is not a secret."""
    (tmp_path / ".env.example").write_text("API_KEY=\n", encoding="utf-8")
    ex = LocalToolExecutor(root=tmp_path)
    out = ex.execute(ToolCall(name="read", arguments={"path": ".env.example"}))
    assert out.ok, "documentation file should stay readable"


def test_i4_sensitive_predicate():
    from pathlib import Path

    assert is_sensitive_file(Path(".env"))
    assert is_sensitive_file(Path("id_rsa"))
    assert is_sensitive_file(Path("x.pem"))
    assert not is_sensitive_file(Path(".env.example"))
    assert not is_sensitive_file(Path("README.md"))


def test_i4_grep_skips_credential_stores(tmp_path):
    """``grep`` must not surface a secret even though it walks the tree."""
    (tmp_path / ".env").write_text("SECRET=hunter2\n", encoding="utf-8")
    (tmp_path / "ok.txt").write_text("SECRET=public\n", encoding="utf-8")
    ex = LocalToolExecutor(root=tmp_path)
    out = ex.execute(ToolCall(name="grep", arguments={"pattern": "SECRET"}))
    assert out.ok
    assert "hunter2" not in (out.output or ""), "grep leaked a secret value"


# ---------------------------------------------------------------------------
# T3/D2 — hostile genome import (SH-02)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "payload",
    ["not-a-list", "abc", [1, 2, 3], [None], [[], {}],
     [{"agent_id": "ok", "generation": "bad", "runs": "x", "standing": "zz"}]],
)
def test_t3_genome_import_never_raises(tmp_path, payload):
    pytest.importorskip("src.novamind.core.session_store")
    from src.novamind.core.session_store import SessionStore

    store = SessionStore(db_path=tmp_path / "s.db")
    # Must not raise — a boundary that raises turns into an HTTP 500.
    result = store.genome_import(payload)  # type: ignore[arg-type]
    assert isinstance(result, int)


def test_t3_genome_import_still_works(tmp_path):
    pytest.importorskip("src.novamind.core.session_store")
    from src.novamind.core.session_store import SessionStore

    store = SessionStore(db_path=tmp_path / "s.db")
    n = store.genome_import([{"agent_id": "agent-x", "name": "X", "runs": 3}])
    assert n == 1


# ---------------------------------------------------------------------------
# I1 — /api/diag discloses no absolute path
# ---------------------------------------------------------------------------
def test_i1_diag_has_no_absolute_paths():
    pytest.importorskip("fastapi")
    import importlib

    from fastapi.testclient import TestClient

    try:
        mod = importlib.import_module("nexus_agent")
    except Exception as exc:  # pragma: no cover - env dependent
        pytest.skip(f"gateway import unavailable: {exc}")
    client = TestClient(mod.app)
    resp = client.get("/api/diag")
    assert resp.status_code == 200
    body = resp.json()
    assert body["loaded_from"] == "nexus_agent.py"
    assert "sys_path_head" not in body
    assert "/data/data/com.termux" not in json.dumps(body)
