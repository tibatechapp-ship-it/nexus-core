"""Tests for src.mcp.git_tools — read-only git inspection."""

from __future__ import annotations

import subprocess
from shutil import which
from types import SimpleNamespace

import pytest

from src.mcp import git_tools as git

pytestmark = pytest.mark.skipif(which("git") is None, reason="git not installed")


def _repo(tmp_path):  # noqa: ANN001, ANN202
    cfg = ["-c", "user.email=t@e.st", "-c", "user.name=Test"]
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "f.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", *cfg, "commit", "-qm", "first commit"], cwd=tmp_path, check=True)
    return tmp_path


# ── availability ──────────────────────────────────────────────────────────
def test_git_available():
    assert git.git_available() is True


# ── real repository ───────────────────────────────────────────────────────
def test_status_log_branches_show(tmp_path):
    repo = _repo(tmp_path)
    assert "##" in git.git_status(repo)
    assert "first commit" in git.git_log(repo)
    assert git.git_branches(repo).strip()
    assert "first commit" in git.git_show(repo, "HEAD", stat_only=True)


def test_diff_empty_when_clean(tmp_path):
    repo = _repo(tmp_path)
    assert git.git_diff(repo) == ""


def test_diff_shows_modification(tmp_path):
    repo = _repo(tmp_path)
    (repo / "g.txt").write_text("keep\n", encoding="utf-8")
    subprocess.run(["git", "add", "g.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e.st", "-c", "user.name=Test", "commit", "-qm", "second"],
        cwd=repo,
        check=True,
    )
    (repo / "f.txt").write_text("one\ntwo\n", encoding="utf-8")
    assert "+two" in git.git_diff(repo)
    assert "+two" in git.git_diff(repo, path="f.txt")
    assert "+two" not in git.git_diff(repo, path="g.txt")  # path scoping honoured


# ── argument building / validation (recorder) ─────────────────────────────
def test_diff_argv_with_staged_and_ref(tmp_path, monkeypatch):
    seen: list[list[str]] = []

    def fake_run(root, args, timeout=git._TIMEOUT):  # noqa: ANN001, ANN202
        seen.append(args)
        return ""

    monkeypatch.setattr(git, "_run", fake_run)
    git.git_diff(tmp_path, ref="HEAD~1", staged=True, path="a/b.txt")
    assert seen[0] == ["diff", "--staged", "HEAD~1", "--", "a/b.txt"]


def test_log_limit_is_clamped(tmp_path, monkeypatch):
    seen: list[list[str]] = []
    monkeypatch.setattr(git, "_run", lambda root, args, timeout=git._TIMEOUT: seen.append(args) or "")
    git.git_log(tmp_path, limit=0)  # below floor -> clamped to 1
    git.git_log(tmp_path, limit=10_000)  # above cap -> 200
    git.git_log(tmp_path, limit="nope")  # non-int -> default
    assert seen[0] == ["log", "--oneline", "-n1"]
    assert seen[1] == ["log", "--oneline", "-n200"]
    assert seen[2] == ["log", "--oneline", "-n10"]


def test_diff_path_escape_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(git, "_run", lambda root, args, timeout=git._TIMEOUT: "")
    with pytest.raises(git.GitError):
        git.git_diff(tmp_path, path="../../etc/passwd")
    with pytest.raises(git.GitError, match="must be a string"):
        git.git_diff(tmp_path, path=5)
    assert git.git_diff(tmp_path, path=None) == ""
    assert git.git_diff(tmp_path, path="") == ""


def test_show_requires_nonempty_ref(tmp_path):
    with pytest.raises(git.GitError):
        git.git_show(tmp_path, "")
    with pytest.raises(git.GitError):
        git.git_show(tmp_path, "  ")


# ── error mapping ─────────────────────────────────────────────────────────
def test_missing_git_binary(tmp_path, monkeypatch):
    def boom(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise FileNotFoundError

    monkeypatch.setattr(git.subprocess, "run", boom)
    with pytest.raises(git.GitError, match="not found"):
        git.git_status(tmp_path)


def test_timeout_becomes_git_error(tmp_path, monkeypatch):
    def boom(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise subprocess.TimeoutExpired(cmd="git status", timeout=1)

    monkeypatch.setattr(git.subprocess, "run", boom)
    with pytest.raises(git.GitError, match="timed out"):
        git.git_status(tmp_path)


def test_nonzero_exit_surfaces_stderr(tmp_path, monkeypatch):
    monkeypatch.setattr(
        git.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=128, stdout="", stderr="fatal: boom\n"),
    )
    with pytest.raises(git.GitError, match="fatal: boom"):
        git.git_status(tmp_path)


def test_nonzero_without_stderr_uses_code(tmp_path, monkeypatch):
    monkeypatch.setattr(
        git.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=3, stdout="", stderr=""),
    )
    with pytest.raises(git.GitError, match=r"\(3\)"):
        git.git_status(tmp_path)
