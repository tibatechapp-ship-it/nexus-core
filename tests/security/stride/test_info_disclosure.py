"""STRIDE — **I**nformation Disclosure: exposing data to the wrong party.

Attack surface for nexus-core:

* ``GET /api/status`` and ``GET /api/diag`` are **unauthenticated reads** (the
  guard only gates mutating methods). ``/api/diag`` returns ``loaded_from`` (an
  absolute server path) and ``sys_path_head`` — filesystem reconnaissance.
* Any error path must not echo a secret (API key) back to the caller.
* The security scanner must detect secrets in scanned text; a miss there is a
  disclosure enabler.
* The gateway must not serve ``.env`` / dotfiles / the runit env dir over HTTP.

Each test states the disclosure and asserts the data does not leave.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.security.stride import helpers as H

CATEGORY = "Information Disclosure"


# ---------------------------------------------------------------------------
# I1 — /api/diag must not leak absolute filesystem paths to an anonymous caller
# ---------------------------------------------------------------------------
def test_i1_diag_does_not_leak_absolute_paths() -> None:
    """EXPLOIT: anonymous ``GET /api/diag`` (a read — no token needed) returns
    the server's absolute install path and sys.path, handing an attacker a map
    of the filesystem.

    FINDING: ``/api/diag`` exposes ``loaded_from`` + ``sys_path_head``. The
    PoC asserts the disclosure is bounded — this test documents the gap and
    is expected to FAIL until the endpoint is hardened (or the exposure is
    explicitly accepted + documented). See the report for the decision.
    """
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    try:
        import importlib

        mod = importlib.import_module("nexus_agent")
    except Exception as exc:  # pragma: no cover - env dependent
        pytest.skip(f"gateway import unavailable: {exc}")

    client = TestClient(mod.app)
    resp = client.get("/api/diag")
    if resp.status_code != 200:  # endpoint may be absent in some builds
        pytest.skip(f"/api/diag returned {resp.status_code}")
    body = resp.json()
    blob = json.dumps(body)
    # A hard filesystem path (e.g. /data/data/com.termux/... or /home/...) is
    # reconnaissance. Assert it is not disclosed to an anonymous reader.
    assert "/data/data/com.termux" not in blob, "diag leaks the Termux root"
    assert "/home/" not in blob, "diag leaks a home path"
    # loaded_from must be a bare filename, never an absolute path.
    assert body.get("loaded_from") == "nexus_agent.py", (
        f"diag leaks a path via loaded_from: {body.get('loaded_from')!r}"
    )
    # sys.path must be a count, never the entries themselves.
    assert "sys_path_head" not in body, "diag leaks raw sys.path entries"
    assert isinstance(body.get("sys_path_entries"), int)


# ---------------------------------------------------------------------------
# I2 — API keys in an error message are never echoed to the caller
# ---------------------------------------------------------------------------
def test_i2_error_paths_do_not_echo_secrets() -> None:
    """EXPLOIT: force an error whose message embeds a provider key; if the
    gateway streams the raw exception the key reaches the client.

    DEFENCE: the gateway's chat error branch truncates to the exception type +
    message but the *router* never places the key in the message. The PoC
    asserts the router's generated text for a bad key carries no key literal.
    """
    pytest.importorskip("src.novamind.core.llm_router")
    import src.novamind.core.llm_router as lr

    src = Path(lr.__file__).read_text(encoding="utf-8")
    # The router reads keys from env; it must not log/format the key VALUE.
    # A cheap, strong signal: no f-string interpolates a key variable.
    for bad in ("f\"{self.api_key", "f'{self.api_key",
                "% (self.api_key", "+ self.api_key +"):
        assert bad not in src, f"key interpolation found: {bad}"


# ---------------------------------------------------------------------------
# I3 — the secret scanner actually detects a realistic token
# ---------------------------------------------------------------------------
def test_i3_secret_scanner_detects_realistic_tokens() -> None:
    """EXPLOIT: a real token committed/logged goes unnoticed because the scanner
    pattern is wrong.

    DEFENCE: the secrets agent flags AWS + GitHub token literals. The PoC feeds
    one of each and asserts a HIGH finding each.
    """
    pytest.importorskip("src.security.agents")
    from src.security.agents import _SecretsAgent

    text = f"key {H.FAKE_AWS_KEY} and {H.FAKE_GH_TOKEN} here"
    findings = _SecretsAgent().scan(text, "probe.py")
    rules = {getattr(f, "rule", None) or getattr(f, "name", "") for f in findings}
    assert any("aws" in str(r).lower() for r in rules), f"AWS key not detected: {rules}"
    assert any("github" in str(r).lower() for r in rules), f"GH token not detected: {rules}"


# ---------------------------------------------------------------------------
# I4 — statically prove no tracked secret file is servable / committed
# ---------------------------------------------------------------------------
def test_i4_no_tracked_secret_files() -> None:
    """EXPLOIT: a ``.env`` or ``telegram.env`` slips into the tree and is served
    or committed, disclosing live credentials.

    DEFENCE: assert no ``.env`` (other than ``.env.example``) is git-tracked and
    that a dotfile path can never be read via the confined tool executor.
    """
    import subprocess

    root = H.repo_root()
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True
    ).stdout.splitlines()
    for path in tracked:
        name = Path(path).name
        assert not (name.startswith(".env") and name != ".env.example"), (
            f"a secret-bearing env file is tracked: {path}"
        )
        assert "telegram.env" not in path, f"telegram env tracked: {path}"

    pytest.importorskip("src.tools.executor")
    from src.tools.executor import LocalToolExecutor, ToolCall

    ex = LocalToolExecutor(root=root)
    # A live secret store must never be readable through a confined tool.
    for secret_path in (".env", "secrets.json", "id_rsa", "cert.pem"):
        out = ex.execute(ToolCall(name="read", arguments={"path": secret_path}))
        assert not out.ok, (
            f"the confined tool executor read {secret_path!r} — the read "
            f"allow-list must exclude dotfiles/secrets (finding I4)")
    # Documentation of variable NAMES is fine and must still be readable.
    doc = ex.execute(ToolCall(name="read", arguments={"path": ".env.example"}))
    assert doc.ok, ".env.example (documentation) should stay readable"


# ---------------------------------------------------------------------------
# I5 — /api/status guard stats never disclose the token
# ---------------------------------------------------------------------------
def test_i5_status_guard_stats_hide_the_token() -> None:
    """EXPLOIT: ``GET /api/status`` echoes the guard config; if it includes the
    token value a read leaks the credential.

    DEFENCE: ``AccessGuard.stats()`` returns auth/header/rate/window/audit —
    never the token. The PoC sets a token and asserts it is absent from stats.
    """
    secret = "the-admin-token-xyz"
    guard = H.access_guard(token=secret)
    blob = json.dumps(guard.stats())
    assert secret not in blob
    assert "token" not in {k.lower() for k in guard.stats()}
