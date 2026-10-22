"""Security tests for src.agent_loop.tools file operations.

Every read_file / write_file / list_files call must stay inside the
workspace root, skip sensitive files (.env, keys, certs), skip build dirs,
reject syntax errors before writing .py, and write atomically.
"""

from __future__ import annotations


import pytest

from src.agent_loop.tools import build_default_registry, safe_path


@pytest.fixture
def reg():
    return build_default_registry()


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """Isolate cwd to tmp_path and workspace env to same."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEXUS_AGENT_WORKSPACE", str(tmp_path))
    return tmp_path


# ─── safe_path ─────────────────────────────────────────────────────

def test_safe_path_accepts_inside(ws):
    assert safe_path("hello.txt") == (ws / "hello.txt").resolve()


def test_safe_path_rejects_parent_escape(ws):
    with pytest.raises(PermissionError, match="خارج"):
        safe_path("../outside.txt")


def test_safe_path_rejects_absolute_outside(ws):
    with pytest.raises(PermissionError, match="خارج"):
        safe_path("/etc/passwd")


def test_safe_path_rejects_env(ws):
    with pytest.raises(PermissionError, match="حساس"):
        safe_path(".env")


def test_safe_path_rejects_ssh_dir(ws):
    with pytest.raises(PermissionError, match="محظور"):
        safe_path(".ssh/id_rsa")


# ─── read_file ─────────────────────────────────────────────────────

def test_read_file_blocks_env(ws, reg):
    (ws / ".env").write_text("SECRET=xxx")
    out = reg.call("read_file", {"path": ".env"})
    assert "محظور" in out or "حساس" in out


def test_read_file_blocks_ssh_key(ws, reg):
    (ws / ".ssh").mkdir()
    (ws / ".ssh" / "id_rsa").write_text("KEY")
    out = reg.call("read_file", {"path": ".ssh/id_rsa"})
    assert "محظور" in out


def test_read_file_blocks_outside(ws, reg):
    outside = ws.parent / "outside.txt"
    outside.write_text("nope")
    out = reg.call("read_file", {"path": str(outside)})
    assert "محظور" in out


def test_read_file_respects_max_size(ws, reg):
    (ws / "big.txt").write_bytes(b"x" * (600 * 1024))
    out = reg.call("read_file", {"path": "big.txt"})
    assert "كبير" in out


def test_read_file_normal_works(ws, reg):
    (ws / "hello.txt").write_text("hi there")
    out = reg.call("read_file", {"path": "hello.txt"})
    assert "hi there" in out


# ─── write_file ────────────────────────────────────────────────────

def test_write_file_blocks_outside(ws, reg):
    out = reg.call("write_file", {"path": "../evil.py", "content": "print(1)"})
    assert "محظور" in out
    assert not (ws.parent / "evil.py").exists()


def test_write_file_blocks_env(ws, reg):
    out = reg.call("write_file", {"path": ".env", "content": "SECRET=x"})
    assert "محظور" in out or "حساس" in out
    assert not (ws / ".env").exists()


def test_write_file_rejects_syntax_error(ws, reg):
    out = reg.call("write_file", {"path": "broken.py", "content": "def broken(:"})
    assert "صياغة" in out
    assert not (ws / "broken.py").exists()


def test_write_file_atomic_no_leftover(ws, reg):
    out = reg.call("write_file", {"path": "ok.py", "content": "print(1)"})
    assert "تم الكتابة" in out
    assert (ws / "ok.py").exists()
    assert not list(ws.glob(".agent-tmp-*"))


def test_write_file_oversize_rejected(ws, reg):
    out = reg.call("write_file", {"path": "big.txt", "content": "x" * (1200 * 1024)})
    assert "كبير" in out


# ─── list_files ────────────────────────────────────────────────────

def test_list_files_skips_sensitive(ws, reg):
    (ws / "hello.txt").write_text("ok")
    (ws / ".env").write_text("secret")
    (ws / "id_rsa").write_text("key")
    out = reg.call("list_files", {"directory": "."})
    assert "hello.txt" in out
    assert ".env" not in out
    assert "id_rsa" not in out


def test_list_files_skips_cache_dirs(ws, reg):
    (ws / "__pycache__").mkdir()
    (ws / "hello.txt").write_text("ok")
    out = reg.call("list_files", {"directory": "."})
    assert "hello.txt" in out
    assert "__pycache__" not in out


def test_list_files_blocks_outside(ws, reg):
    out = reg.call("list_files", {"directory": str(ws.parent)})
    assert "محظور" in out
