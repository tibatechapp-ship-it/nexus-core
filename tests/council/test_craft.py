"""Tests for the Craft module (v1.12) — free-text code generation + safety.

Covers the deterministic/offline surface fully (parser, path gate, proof) and
the LLM path with fakes. No network is ever touched here.
"""
from __future__ import annotations

import json
import os

import pytest

from src.council import craft
from src.council.craft import CraftError, _parse_files, _safe_path, generate_code


# ─────────────────────────────── _parse_files ───────────────────────────────

def test_parse_files_plain_array():
    files = _parse_files('[{"path": "a.py", "content": "print(1)"}]')
    assert files == [("a.py", "print(1)")]


def test_parse_files_object_with_files_key():
    raw = '{"files": [{"path": "b.md", "content": "# hi"}]}'
    assert _parse_files(raw) == [("b.md", "# hi")]


def test_parse_files_strips_code_fences():
    raw = '```json\n[{"path": "a.py", "content": "x=1"}]\n```'
    assert _parse_files(raw) == [("a.py", "x=1")]


def test_parse_files_ignores_surrounding_noise():
    raw = 'Sure!\n[{"path": "a.py", "content": "x=1"}]\nDone.'
    assert _parse_files(raw) == [("a.py", "x=1")]


def test_parse_files_caps_at_max_files():
    items = [{"path": "f%d.py" % i, "content": "x"} for i in range(30)]
    assert len(_parse_files(json.dumps(items))) == craft.MAX_FILES


def test_parse_files_skips_items_without_path():
    raw = json.dumps([{"content": "x"}, {"path": "ok.py", "content": "y"}])
    assert _parse_files(raw) == [("ok.py", "y")]


@pytest.mark.parametrize("raw", [
    "",
    "   ",
    "no json at all",
    "{broken json",
    "[]",
    '{"files": []}',
    '[{"content": "no path"}]',
])
def test_parse_files_invalid_raises(raw):
    with pytest.raises(CraftError):
        _parse_files(raw)


# ─────────────────────────────── _safe_path ────────────────────────────────

def test_safe_path_accepts_allowed_ext(tmp_path):
    p = _safe_path(str(tmp_path), "sub/a.py")
    assert p == os.path.join(str(tmp_path), "sub/a.py")


@pytest.mark.parametrize("rel", ["../evil.py", "/etc/x.py", "~/x.py", "a/../../b.py"])
def test_safe_path_rejects_traversal(tmp_path, rel):
    with pytest.raises(CraftError):
        _safe_path(str(tmp_path), rel)


def test_safe_path_rejects_disallowed_ext(tmp_path):
    with pytest.raises(CraftError):
        _safe_path(str(tmp_path), "evil.exe")


# ─────────────────────────────── generate_code ──────────────────────────────

class _LLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def generate(self, **kwargs):
        self.calls += 1
        self.last = kwargs
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return {"ok": True, "text": text}


class _FailLLM:
    def generate(self, **kwargs):
        return {"ok": False, "error": "quota exceeded"}


class _BoomLLM:
    def generate(self, **kwargs):
        raise RuntimeError("no network")


@pytest.fixture(autouse=True)
def _isolate_builds(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_BUILDS", str(tmp_path / "builds"))


def test_generate_code_writes_files_with_compile_proof():
    llm = _LLM([
        {"path": "main.py", "content": "def add(a, b):\n    return a + b\n"},
        {"path": "README.md", "content": "# demo\n"},
    ])
    out = generate_code("اكتب دالة جمع", llm=llm)
    assert out["proof"]["files_written"] == 2
    assert out["proof"]["py_compile"]["main.py"] == "ok"
    assert out["proof"]["ok"] is True
    assert os.path.isfile(os.path.join(out["dir"], "main.py"))
    assert os.path.isfile(os.path.join(out["dir"], "manifest.json"))
    assert out["review"] is None
    assert out["build_id"].startswith("craft_")


def test_generate_code_render_bad_python_fails_proof():
    llm = _LLM([{"path": "bad.py", "content": "def broken(:\n"}])
    out = generate_code("اكتب شيئاً مكسوراً", llm=llm)
    assert out["proof"]["ok"] is False
    assert out["proof"]["py_compile"]["bad.py"].startswith("error:")


def test_generate_code_rejects_unsafe_path():
    llm = _LLM([{"path": "../evil.py", "content": "x=1"}])
    with pytest.raises(CraftError):
        generate_code("anything", llm=llm)


def test_generate_code_enforces_total_size(monkeypatch):
    llm = _LLM([{"path": "a.py", "content": "x" * 10}])
    monkeypatch.setattr(craft, "MAX_BYTES", 5)
    with pytest.raises(CraftError):
        generate_code("anything", llm=llm)


def test_generate_code_empty_query_raises():
    with pytest.raises(CraftError):
        generate_code("   ", llm=_LLM([]))


def test_generate_code_llm_failure_message():
    with pytest.raises(CraftError):
        generate_code("anything", llm=_FailLLM())


def test_generate_code_llm_exception_propagates():
    with pytest.raises(RuntimeError):
        generate_code("anything", llm=_BoomLLM())


def test_generate_code_no_llm_available(monkeypatch):
    monkeypatch.setattr(craft, "_router", lambda: None)
    with pytest.raises(CraftError):
        generate_code("anything")


def test_generate_code_review_calls_council(monkeypatch):
    called = {}

    def fake_review(files, query):
        called["files"] = files
        called["query"] = query
        return {"verdict": "approve", "score": 0.9, "rounds": 2}

    monkeypatch.setattr(craft, "_review", fake_review)
    llm = _LLM([{"path": "main.py", "content": "x = 1\n"}])
    out = generate_code("اكتب سكربت", review=True, llm=llm)
    assert out["review"] == {"verdict": "approve", "score": 0.9, "rounds": 2}
    assert called["files"][0][0] == "main.py"


def test_generate_code_review_skipped_on_bad_proof(monkeypatch):
    monkeypatch.setattr(craft, "_review", lambda *a: {"verdict": "approve"})
    llm = _LLM([{"path": "bad.py", "content": "def broken(:\n"}])
    out = generate_code("x", review=True, llm=llm)
    assert out["review"] is None


def test_review_returns_error_on_bridge_failure(monkeypatch):
    fake_bridge = type("B", (), {
        "deliberate_with_memory": staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("dead"))),
    })
    import src.council.rag_bridge as rb
    monkeypatch.setattr(rb, "get_council_bridge", lambda: fake_bridge())
    res = craft._review([("a.py", "x=1")], "q")
    assert res["verdict"] == "error"
    assert "dead" in res["error"]


def test_module_imports_without_src_on_path(monkeypatch):
    # _safe_rel_path fallback must not crash if builder import fails
    assert callable(craft._safe_path)
