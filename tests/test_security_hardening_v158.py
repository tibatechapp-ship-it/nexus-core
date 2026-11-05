"""Regression tests for the v1.58.0 security-hardening wave (ض1..ض10).

Each test maps 1:1 to a finding of the static security review adopted in
v1.58.0: the docstring states the exploit and asserts the defence.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS = _ROOT / ".github" / "workflows"

# ═══════════════════════════════ ض1 — VFS containment ═══════════════════════


def _vfs_with_root(monkeypatch: pytest.MonkeyPatch, root: Path):
    from src.novamind.core import vfs as vfs_mod

    monkeypatch.setattr(vfs_mod, "PROJECT_ROOT", root)
    return vfs_mod, vfs_mod.SafeVfs()


def test_d1_vfs_rejects_absolute_path_outside_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EXPLOIT: an agent asks vfs to read an absolute secret anywhere on disk.

    DEFENCE: every operation resolves then requires containment in the root.
    """
    vfs_mod, v = _vfs_with_root(monkeypatch, tmp_path)
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("top secret", encoding="utf-8")

    with pytest.raises(vfs_mod.VfsError) as err:
        v.read(str(outside))
    assert err.value.code == "FORBIDDEN_PATH"
    with pytest.raises(vfs_mod.VfsError):
        v.write(str(outside), "x")
    with pytest.raises(vfs_mod.VfsError):
        v.delete(str(outside))
    assert v.exists(str(outside)) is False
    assert v.list_dir(str(tmp_path.parent)) == []


def test_d1_vfs_rejects_symlink_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EXPLOIT: a symlink inside the workspace points to a file outside.

    DEFENCE: resolution happens before the containment check.
    """
    vfs_mod, v = _vfs_with_root(monkeypatch, tmp_path)
    secret = tmp_path.parent / "vault.txt"
    secret.write_text("classified", encoding="utf-8")
    (tmp_path / "leak.txt").symlink_to(secret)
    with pytest.raises(vfs_mod.VfsError):
        v.read("leak.txt")


def test_d1_vfs_sibling_prefix_root_is_not_confused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sibling whose name extends the root's name is still outside."""
    vfs_mod, v = _vfs_with_root(monkeypatch, tmp_path / "work")
    (tmp_path / "work").mkdir()
    sibling = tmp_path / "work-other"
    sibling.mkdir()
    (sibling / "f.txt").write_text("x", encoding="utf-8")
    with pytest.raises(vfs_mod.VfsError):
        v.read(str(sibling / "f.txt"))
    # containment never blocks the root itself
    (tmp_path / "work" / "ok.txt").write_text("in", encoding="utf-8")
    assert v.read(str(tmp_path / "work" / "ok.txt")) == "in"


# ═══════════════════ ض2 — shell tools are opt-in, allowlist trimmed ═════════


def _import_shell_tools_with_env(env: dict) -> subprocess.CompletedProcess:
    """Run a probe in a clean interpreter: is run_command registered?"""
    code = (
        "import sys; sys.path.insert(0, 'src'); sys.path.insert(0, 'src/novamind')\n"
        "import novamind.tools.shell_tools as st\n"
        "print('run_command' in st.registry.tools, 'run_python' in st.registry.tools)\n"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_ROOT),
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_d2_shell_tools_disabled_by_default() -> None:
    """EXPLOIT: any deployment importing the tools module silently exposes
    code-execution tools to agents.

    DEFENCE: registration requires NEXUS_ENABLE_SHELL_TOOLS=1 explicitly.
    """
    probe = _import_shell_tools_with_env({})
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == "False False"


def test_d2_shell_tools_register_only_with_explicit_opt_in() -> None:
    probe = _import_shell_tools_with_env({"NEXUS_ENABLE_SHELL_TOOLS": "1"})
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == "True True"


def test_d2_interpreters_network_and_destructive_are_not_whitelisted() -> None:
    """The allowlist is convenience, not a boundary: interpreters, fetchers
    and destructive binaries were removed from it entirely."""
    from novamind.tools.shell_tools import SAFE_COMMANDS, RunCommandTool

    for banned in ("python3", "pip3", "curl", "wget", "rm", "chmod"):
        assert banned not in SAFE_COMMANDS, banned
    tool = RunCommandTool()
    for cmd in ("python3 -c 'print(1)'", "curl http://evil.example", "rm -rf x"):
        res = tool.run(cmd, timeout=5)
        assert res.ok is False and "not allowed" in (res.error or ""), cmd


def test_d2_git_is_restricted_to_read_only_subcommands() -> None:
    from novamind.tools.shell_tools import RunCommandTool

    tool = RunCommandTool()
    res = tool.run("git push origin main", timeout=10)
    assert res.ok is False and "read-only" in (res.error or "")
    res = tool.run("git config user.name x", timeout=10)
    assert res.ok is False and "read-only" in (res.error or "")
    ok = tool.run("git status --porcelain", timeout=30)
    assert ok.ok is True  # read-only subcommand passes


# ═══════════════════ ض3 — grep never reads outside the root ═════════════════


def test_d3_grep_skips_symlink_pointing_outside(tmp_path: Path) -> None:
    """EXPLOIT: plant a symlink inside the workspace → grep reads the secret.

    DEFENCE: _walk_text_files re-resolves every candidate and skips any that
    escapes the root.
    """
    from src.tools.executor import LocalToolExecutor

    root = tmp_path / "ws"
    root.mkdir()
    (root / "note.txt").write_text("hello grep", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("SECRET_TOKEN_OUTSIDE", encoding="utf-8")
    (root / "leak.txt").symlink_to(secret)

    ex = LocalToolExecutor(root=root)
    out = ex._grep({"pattern": "TOKEN", "path": "."})
    assert out == "(no matches)"
    out2 = ex._grep({"pattern": "grep", "path": "."})
    assert "note.txt" in out2  # normal files still searchable


# ═══════════════════ ض4 — sandbox target containment by path ════════════════


def test_d4_safe_target_rejects_sibling_prefix(tmp_path: Path) -> None:
    """EXPLOIT: workdir /tmp/work, plan path /tmp/work-other/file — the old
    textual startswith check accepted the escape.

    DEFENCE: is_relative_to path comparison.
    """
    from src.coder.sandbox import _safe_target

    root = tmp_path / "work"
    root.mkdir()
    sibling = tmp_path / "work-other"
    sibling.mkdir()
    with pytest.raises(ValueError, match="escapes sandbox"):
        _safe_target(root, str(sibling / "file.txt"))


# ═══════════════════ ض5 — bounded capture + group kill ══════════════════════


def test_d5_run_cmd_caps_output_while_reading(tmp_path: Path) -> None:
    """DEFENCE: stdout is bounded during the drain (memory), the child is
    never killed by the cap, and the truncation is reported."""
    from src.coder.sandbox import MAX_OUTPUT_BYTES, run_cmd

    res = run_cmd([sys.executable, "-c", "print('y' * 500_000)"], tmp_path)
    assert res["ok"] is True
    assert len(res["stdout"]) <= MAX_OUTPUT_BYTES
    assert res["truncated"] is True


def test_d5_timeout_kills_the_whole_process_group(tmp_path: Path) -> None:
    """EXPLOIT: a timed-out parent leaves grandchildren alive holding pipes.

    DEFENCE: the session's process group gets SIGKILL — verified by probing
    the grandchild's PID (printed by the parent before the kill).
    """
    from src.coder.sandbox import run_cmd

    script = (
        "import subprocess, time\n"
        "child = subprocess.Popen(['sleep', '30'])\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(30)\n"
    )
    res = run_cmd([sys.executable, "-c", script], tmp_path, timeout=1)
    assert res["timeout"] is True and res["ok"] is False
    grandchild = int(res["stdout"].strip())
    time.sleep(0.5)
    with pytest.raises(ProcessLookupError):
        os.kill(grandchild, 0)


# ═══════════════════ ض6 — explicit mutation semantics ═══════════════════════


def _plan(steps: list):
    from src.coder.plan import RepairPlan

    return RepairPlan(goal="g", defects=[], steps=steps, tests_to_run=["t.py"])


def test_d6_create_refuses_to_overwrite(tmp_path: Path) -> None:
    from src.coder.plan import Step
    from src.coder.sandbox import apply_plan

    (tmp_path / "a.py").write_text("original", encoding="utf-8")
    plan = _plan([Step(file="a.py", action="create", reason="r", patch_hint="new")])
    res = apply_plan(plan, tmp_path)
    assert res["ok"] is False
    assert "refusing to overwrite" in res["errors"][0]["error"]
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "original"


def test_d6_edit_replaces_unique_block(tmp_path: Path) -> None:
    from src.coder.plan import Step
    from src.coder.sandbox import apply_plan

    (tmp_path / "a.py").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    plan = _plan([Step(file="a.py", action="edit", reason="r",
                       patch_hint="BETA", find="beta")])
    res = apply_plan(plan, tmp_path)
    assert res["ok"] is True
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "alpha\nBETA\ngamma\n"


def test_d6_edit_rejects_ambiguous_and_missing_find(tmp_path: Path) -> None:
    from src.coder.plan import Step
    from src.coder.sandbox import apply_plan

    (tmp_path / "a.py").write_text("dup\ndup\n", encoding="utf-8")
    ambiguous = _plan([Step(file="a.py", action="edit", reason="r",
                            patch_hint="x", find="dup")])
    res = apply_plan(ambiguous, tmp_path)
    assert res["ok"] is False and "matched 2 times" in res["errors"][0]["error"]

    no_find = _plan([Step(file="a.py", action="edit", reason="r", patch_hint="x")])
    res = apply_plan(no_find, tmp_path)
    assert res["ok"] is False and "'find' block" in res["errors"][0]["error"]

    missing_target = _plan([Step(file="ghost.py", action="edit", reason="r",
                                 patch_hint="x", find="y")])
    res = apply_plan(missing_target, tmp_path)
    assert res["ok"] is False and "missing" in res["errors"][0]["error"]


def test_d6_unknown_action_is_an_error_not_a_write(tmp_path: Path) -> None:
    from src.coder.plan import Step
    from src.coder.sandbox import apply_plan

    plan = _plan([Step(file="a.py", action="rewrite", reason="r", patch_hint="x")])
    res = apply_plan(plan, tmp_path)
    assert res["ok"] is False and "unknown action" in res["errors"][0]["error"]
    assert not (tmp_path / "a.py").exists()


def test_d6_validation_requires_find_on_edit() -> None:
    from src.coder.plan import Step, validate

    plan = _plan([Step(file="a.py", action="edit", reason="r", patch_hint="x")])
    assert any("'find' block" in e for e in validate(plan))
    ok = _plan([Step(file="a.py", action="edit", reason="r",
                     patch_hint="new", find="old")])
    assert validate(ok) == []


def test_d6_plan_from_json_carries_find() -> None:
    from src.coder.plan import plan_from_json

    plan = plan_from_json({"goal": "g", "steps": [
        {"file": "a.py", "action": "edit", "reason": "r",
         "patch_hint": "new", "find": "old"}], "tests_to_run": ["t"]})
    assert plan.steps[0].find == "old"


# ═══════════════════ ض7/ض8 — CI gates and least privilege ═══════════════════


def test_d7_ruff_is_a_hard_gate_in_ci() -> None:
    """EXPLOIT: `ruff check ... || true` kept the workflow green with lint
    errors — the gate was an announcement, not a gate.

    DEFENCE: no `|| true` on the ruff line, and the tree is ruff-clean.
    """
    import re

    text = (_WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    ruff_lines = [ln for ln in text.splitlines() if "ruff check" in ln]
    assert ruff_lines, "ruff step disappeared from ci.yml"
    for ln in ruff_lines:
        assert "|| true" not in ln, ln
    probe = subprocess.run(
        ["python3", "-m", "ruff", "check", "."],
        cwd=str(_ROOT), capture_output=True, text=True, timeout=120,
    )
    assert probe.returncode == 0, probe.stdout


def test_d8_test_workflow_is_least_privilege() -> None:
    """DEFENCE: workflow default = contents: read; only the publishing job
    that really commits (badge + reports) declares contents: write."""
    import yaml

    data = yaml.safe_load((_WORKFLOWS / "test.yml").read_text(encoding="utf-8"))
    assert data["permissions"] == {"contents": "read"}
    badge = data["jobs"]["coverage-badge"]
    assert badge["permissions"] == {"contents": "write"}
    for name, job in data["jobs"].items():
        if name != "coverage-badge":
            assert "write" not in str(job.get("permissions", {})), name


# ═══════════════════ ض9 — unified guard on the web app ══════════════════════


def test_d9_web_app_guard_requires_token_for_mutations(monkeypatch) -> None:
    """EXPLOIT: anyone reaching the dashboard server could trigger agent runs
    and state changes — the guard existed but only the gateway installed it.

    DEFENCE: the same AccessGuard is middleware on the app itself; mutating
    requests need X-Auth-Token, reads stay open.
    """
    from fastapi.testclient import TestClient

    from src.web import app as webapp

    monkeypatch.setattr(webapp.GUARD, "token", "s3cret-token")
    client = TestClient(webapp.app)
    # mutating request without / with wrong token → 401 before routing
    r = client.post("/api/__no_such_route__")
    assert r.status_code == 401
    r = client.post("/api/__no_such_route__", headers={"X-Auth-Token": "wrong"})
    assert r.status_code == 401
    # right token passes the guard (404 = routing, not auth)
    r = client.post("/api/__no_such_route__", headers={"X-Auth-Token": "s3cret-token"})
    assert r.status_code == 404
    # reads never need a token
    r = client.get("/api/__no_such_route__")
    assert r.status_code == 404


def test_d9_web_app_guard_reads_token_from_env(monkeypatch) -> None:
    """GUARD is built from the environment at import (NEXUS_AUTH_TOKEN)."""
    from src.security.access import TOKEN_ENV, AccessGuard

    guard = AccessGuard.from_env({TOKEN_ENV: "env-token"})
    assert guard.auth_enabled is True
    guard2 = AccessGuard.from_env({})
    assert guard2.auth_enabled is False


# ═══════════════════ ض10 — MIZAN workflow cannot be pwned by a PR ═══════════
#
# Found during the v1.58.0 verification pass (not in the external review):
# `.github/workflows/mizan-scan.yml` used `pull_request_target` (write token +
# repo secrets) while checking out and EXECUTING the PR's own Python — a
# textbook pwn-a-PR pipeline. Its `git add .` also committed the scanner's
# working tree: 1200+ files of node_modules, package.json, SARIF stubs.


def _load_workflow(name: str) -> dict:
    import yaml

    path = _WORKFLOWS / name
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_d10_mizan_workflow_uses_pull_request_not_target() -> None:
    """`pull_request_target` runs with repo write tokens and secrets even for
    hostile forks; `pull_request` strips both automatically."""
    data = _load_workflow("mizan-scan.yml")
    assert "pull_request_target" not in data[True]  # `on:` parses as True
    assert "pull_request" in data[True]


def test_d10_mizan_autocommit_excludes_scanner_artifacts() -> None:
    """The bot's commit step must never re-add the scanner working tree."""
    data = _load_workflow("mizan-scan.yml")
    steps = data["jobs"]["mizan-security-scan"]["steps"]
    commit_step = next(s for s in steps if s.get("name") == "Commit and Push Fixes")
    run = commit_step["run"]
    assert "git add ." not in run
    for artifact in (
        "node_modules", "package.json", "package-lock.json",
        "bandit.sarif", "semgrep.sarif", "mizan_report.md",
    ):
        assert f":(exclude){artifact}" in run, artifact


def test_d10_scanner_artifacts_are_gitignored() -> None:
    """`.gitignore` blocks the artifacts even if a future step uses git add."""
    ignored = (_ROOT / ".gitignore").read_text(encoding="utf-8")
    for line in (
        "node_modules/", "package-lock.json", "bandit.sarif",
        "semgrep.sarif", "mizan_report.md",
    ):
        assert line in ignored, line


def test_d10_scanner_artifacts_are_not_tracked() -> None:
    """Nothing under node_modules/ and no SARIF stub is in the index."""
    import shutil
    import subprocess

    if shutil.which("git") is None:  # pragma: no cover - git always in CI
        pytest.skip("git not available")
    out = subprocess.run(
        ["git", "ls-files"], cwd=_ROOT, capture_output=True, text=True,
        timeout=30,
    ).stdout.splitlines()
    tracked = set(out)
    assert not any(p == "node_modules" or p.startswith("node_modules/") for p in tracked)
    for artifact in ("bandit.sarif", "semgrep.sarif", "test_mizan.txt",
                     "package.json", "package-lock.json"):
        assert artifact not in tracked, artifact
