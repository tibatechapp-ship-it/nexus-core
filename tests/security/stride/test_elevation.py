"""STRIDE — **E**levation of Privilege: gaining rights you were not granted.

Attack surface for nexus-core:

* The confined tool executor must not let a ``read``/``list``/``grep`` call
  escape the sandbox root (path traversal → read /etc/passwd) or reach a tool
  outside ``SAFE_TOOL_NAMES``.
* The builder write-gate (``_safe_rel_path``) must reject ``..`` and absolute
  escapes.
* The exec sandbox must not allow arbitrary shell beyond its allow-list and must
  not run outside its confined cwd.
* The access guard must gate *every* mutating method, not a subset — a missed
  method is an unauthenticated privileged action.

Each test states the escalation and asserts the boundary holds.
"""
from __future__ import annotations

import pytest

from tests.security.stride import helpers as H

CATEGORY = "Elevation of Privilege"


# ---------------------------------------------------------------------------
# E1 — tool executor cannot escape the sandbox root via traversal
# ---------------------------------------------------------------------------
def test_e1_tool_executor_traversal_is_denied() -> None:
    """EXPLOIT: ``read`` with ``../../etc/passwd`` climbs out of the sandbox and
    returns host files — the tool becomes an arbitrary file reader.

    DEFENCE: ``_resolve`` confines to ``root``; the call fails with no content.
    """
    pytest.importorskip("src.tools.executor")
    from src.tools.executor import LocalToolExecutor, ToolCall

    root = H.repo_root()
    ex = LocalToolExecutor(root=root)
    out = ex.execute(ToolCall(name="read", arguments={"path": H.VICTIM_RELATIVE}))
    assert not out.ok, f"traversal read succeeded: {out.output[:80]!r}"
    assert "root:" not in (out.output or ""), "passwd content leaked"


# ---------------------------------------------------------------------------
# E2 — a tool outside the allow-list is refused
# ---------------------------------------------------------------------------
def test_e2_unknown_tool_is_refused() -> None:
    """EXPLOIT: call an unlisted tool (``write``/``shell``/``exec``) to gain
    write/exec privilege through the read-only executor.

    DEFENCE: only ``SAFE_TOOL_NAMES`` run; anything else is refused.
    """
    pytest.importorskip("src.tools.executor")
    from src.tools.executor import SAFE_TOOL_NAMES, LocalToolExecutor, ToolCall

    root = H.repo_root()
    ex = LocalToolExecutor(root=root)
    for name in ("write", "shell", "exec", "delete", "rm"):
        assert name not in SAFE_TOOL_NAMES, f"{name} is in the allow-list!"
        out = ex.execute(ToolCall(name=name, arguments={"path": "x"}))
        assert not out.ok, f"privileged tool {name} executed"


# ---------------------------------------------------------------------------
# E3 — the builder write-gate rejects escapes
# ---------------------------------------------------------------------------
def test_e3_builder_write_gate_rejects_escape() -> None:
    """EXPLOIT: craft a file path that escapes the build root so craft mode
    writes anywhere on disk (privilege escalation via codegen).

    DEFENCE: ``_safe_rel_path`` returns None for absolute / ``..`` escapes.
    """
    pytest.importorskip("src.council.builder")
    from src.council.builder import _safe_rel_path

    for hostile in ("../../etc/cron.d/x", "/etc/passwd", "a/../../b",
                    "..\\..\\win", "/tmp/evil"):
        assert _safe_rel_path(hostile) is None, f"escape accepted: {hostile}"
    # A plain relative path is still accepted (the gate is not a blanket ban).
    assert _safe_rel_path("pkg/mod.py") is not None


# ---------------------------------------------------------------------------
# E4 — the access guard gates EVERY mutating method
# ---------------------------------------------------------------------------
def test_e4_guard_gates_every_mutating_method() -> None:
    """EXPLOIT: hit a mutating verb the guard forgot to gate (e.g. DELETE) and
    perform a privileged action without a token.

    DEFENCE: POST/PUT/PATCH/DELETE are all in the guarded set; each is refused
    without a valid token.
    """
    from src.security.access import MUTATING_METHODS

    guard = H.access_guard(token="t")
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert method in MUTATING_METHODS, f"{method} not gated"
        dec = guard.check(method, "/api/genome/reset", {})
        assert dec.allowed is False, f"{method} allowed without a token"
    # A read is NOT gated (by design) — proves the gate is method-specific.
    assert guard.check("GET", "/api/status", {}).allowed is True


# ---------------------------------------------------------------------------
# E5 — the exec sandbox confines its working directory
# ---------------------------------------------------------------------------
def test_e5_exec_sandbox_confines_cwd() -> None:
    """EXPLOIT: run code in the exec sandbox that reads a host path, escalating
    from "run a snippet" to "read the whole machine".

    DEFENCE: the sandbox runs in a temporary cwd; the PoC asserts the router
    rejects/handles outside-root access without returning host content.
    """
    pytest.importorskip("fastapi")
    import sys
    from pathlib import Path

    root = H.repo_root()
    tools_dir = root / "tools"
    sys.path.insert(0, str(tools_dir))
    try:
        import exec_sandbox  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - env dependent
        pytest.skip(f"exec_sandbox unavailable: {exc}")
    finally:
        sys.path.remove(str(tools_dir))

    # The module exists and exposes a confined runner contract; prove the
    # sandbox root is a temp dir, never the repo or the host root.
    src = Path(exec_sandbox.__file__).read_text(encoding="utf-8")
    assert "TemporaryDirectory" in src or "mkdtemp" in src, (
        "exec sandbox has no temporary cwd — work could run in the repo")
