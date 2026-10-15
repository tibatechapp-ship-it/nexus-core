"""Tests for the Council Builder (offline/deterministic paths + safety)."""
from __future__ import annotations

import json
import os

import pytest

from src.council.builder import (
    Builder,
    BuildFile,
    get_build,
    list_builds,
    _safe_rel_path,
)
from src.council.engine import CouncilResult


def _result(verdict="approve", score=0.85, consensus=True, rounds=2,
            recommendation="استخدم sqlite"):
    transcript = [{
        "phase": "independent", "member": "analyst",
        "response": "آمن: جيد\n[الحكم: موافق]\n[التوصية: " + recommendation + "]",
    }]
    return CouncilResult(verdict=verdict, score=score, consensus=consensus,
                         rounds=rounds, transcript=transcript, elapsed=1.0)


class _FakeLLM:
    def __init__(self, text):
        self.text = text

    def generate(self, **kwargs):
        return {"ok": True, "text": self.text}


class _BoomLLM:
    def generate(self, **kwargs):
        raise RuntimeError("no network")


# ─────────────────────────── _safe_rel_path ───────────────────────────

@pytest.mark.parametrize("path,expected", [
    ("main.py", "main.py"),
    ("a/b/c.txt", "a/b/c.txt"),
    ("./a/./b.py", "a/b.py"),
    (r"a\b.py", "a/b.py"),
])
def test_safe_rel_path_accepts(path, expected):
    assert _safe_rel_path(path) == expected


@pytest.mark.parametrize("path", [
    "", "   ", "/etc/passwd", "~/x", "../evil.py", "a/../../b",
    "a b.py", "a:b.py", "x" * 201,
])
def test_safe_rel_path_rejects(path):
    assert _safe_rel_path(path) is None


# ─────────────────────────── detect_kind ─────────────────────────────

@pytest.mark.parametrize("q,kind", [
    ("اكتب سكربت بايثون", "code"),
    ("add an API endpoint", "code"),
    ("هل نستخدم sqlite أم json؟", "plan"),
    ("", "plan"),
])
def test_detect_kind(q, kind):
    assert Builder().detect_kind(q) == kind


# ──────────────────────────── plan() ─────────────────────────────────

def test_plan_is_deterministic_and_offline():
    plan = Builder().plan("هل نستخدم sqlite؟", _result())
    paths = [f["path"] for f in plan["files"]]
    assert "PLAN.md" in paths and "decision.json" in paths
    assert plan["kind"] == "plan"
    assert "استخدم sqlite" in plan["summary"]


def test_plan_reject_steps():
    plan = Builder().plan("x", _result(verdict="reject", score=0.1))
    joined = " ".join(plan["steps"])
    assert "لا تنفّذ" in joined


def test_plan_human_review_steps():
    plan = Builder().plan("x", _result(verdict="human_review", score=0.5))
    joined = " ".join(plan["steps"])
    assert "راجع" in joined


# ───────────────────────── parse_blueprint ───────────────────────────

def test_parse_blueprint_plain():
    data = Builder.parse_blueprint('{"title":"t","files":[{"path":"a.py","content":"x"}]}')
    assert data["title"] == "t"
    assert data["files"][0]["path"] == "a.py"


def test_parse_blueprint_with_fences_and_noise():
    raw = 'Sure!\n```json\n{"title":"t","files":[]}\n```\n'
    assert Builder.parse_blueprint(raw)["title"] == "t"


def test_parse_blueprint_files_not_list_is_emptied():
    assert Builder.parse_blueprint('{"title":"t","files":"nope"}')["files"] == []


@pytest.mark.parametrize("raw", ["", "no json here", "{broken", "[1,2,3]", "```\n```"])
def test_parse_blueprint_invalid_returns_none(raw):
    assert Builder.parse_blueprint(raw) is None


# ───────────────────────────── build() ───────────────────────────────

def test_build_offline_writes_plan_and_decision(tmp_path):
    b = Builder(root=str(tmp_path))
    out = b.build("هل نستخدم sqlite؟", _result(), use_llm=False)
    assert out.ok
    names = sorted(os.listdir(out.dir))
    assert "PLAN.md" in names and "decision.json" in names and "manifest.json" in names
    assert out.proof["ok"] is True


def test_build_dedupes_decision_json(tmp_path):
    b = Builder(root=str(tmp_path))
    out = b.build("x", _result(), use_llm=False)
    paths = [f.path for f in out.files]
    assert paths.count("decision.json") == 1


def test_build_rejects_unsafe_paths(tmp_path):
    llm = _FakeLLM(json.dumps({
        "title": "t", "kind": "code", "summary": "s", "steps": [],
        "files": [
            {"path": "../evil.py", "content": "x"},
            {"path": "/etc/passwd", "content": "x"},
            {"path": "ok.py", "content": "print(1)\n"},
        ],
    }))
    out = Builder(root=str(tmp_path), llm=llm).build("اكتب كود", _result())
    names = sorted(os.listdir(out.dir))
    assert "ok.py" in names
    assert "evil.py" not in names and "passwd" not in names
    manifest = get_build(out.build_id, str(tmp_path))
    assert "../evil.py" in manifest["skipped"]


def test_build_proof_marks_broken_py(tmp_path):
    llm = _FakeLLM(json.dumps({
        "title": "t", "kind": "code", "files": [
            {"path": "bad.py", "content": "def (:\n"},
        ],
    }))
    out = Builder(root=str(tmp_path), llm=llm).build("اكتب كود", _result())
    assert out.proof["py_compile"]["bad.py"].startswith("error")
    assert out.ok is False


def test_build_always_adds_plan_md(tmp_path):
    llm = _FakeLLM(json.dumps({
        "title": "t", "kind": "code", "files": [{"path": "main.py", "content": "print(1)\n"}],
    }))
    out = Builder(root=str(tmp_path), llm=llm).build("اكتب كود", _result())
    assert "PLAN.md" in os.listdir(out.dir)


def test_build_llm_failure_falls_back_to_plan(tmp_path):
    out = Builder(root=str(tmp_path), llm=_BoomLLM()).build("x", _result())
    assert out.kind == "plan"
    assert out.ok


def test_build_invalid_llm_json_falls_back(tmp_path):
    out = Builder(root=str(tmp_path), llm=_FakeLLM("not json")).build("x", _result())
    assert out.kind == "plan"


def test_build_respects_max_files(tmp_path):
    files = [{"path": f"f{i}.txt", "content": "x"} for i in range(Builder.MAX_FILES + 5)]
    llm = _FakeLLM(json.dumps({"title": "t", "kind": "doc", "files": files}))
    out = Builder(root=str(tmp_path), llm=llm).build("x", _result())
    written = [f for f in out.files]
    assert len(written) <= Builder.MAX_FILES
    # الملفات الإلزامية تُحفظ رغم القصّ
    paths = {f.path for f in written}
    assert "decision.json" in paths and "PLAN.md" in paths
    manifest = get_build(out.build_id, str(tmp_path))
    assert manifest["skipped"]


def test_build_skips_oversized_file(tmp_path):
    big = "a" * (Builder.MAX_FILE_BYTES + 1)
    llm = _FakeLLM(json.dumps({
        "title": "t", "kind": "doc",
        "files": [{"path": "big.txt", "content": big}],
    }))
    out = Builder(root=str(tmp_path), llm=llm).build("x", _result())
    assert "big.txt" not in os.listdir(out.dir)


def test_build_accepts_dict_result(tmp_path):
    result = {"verdict": "approve", "score": 0.9, "consensus": True,
              "rounds": 1, "transcript": []}
    out = Builder(root=str(tmp_path)).build("x", result, use_llm=False)
    assert out.ok


# ───────────────────────── list / get ────────────────────────────────

def test_list_and_get_builds(tmp_path):
    b = Builder(root=str(tmp_path))
    out = b.build("x", _result(), use_llm=False)
    listed = list_builds(str(tmp_path))
    assert listed and listed[0]["build_id"] == out.build_id
    assert get_build(out.build_id, str(tmp_path))["build_id"] == out.build_id


def test_list_builds_missing_root_returns_empty(tmp_path):
    assert list_builds(str(tmp_path / "nope")) == []


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "/abs"])
def test_get_build_rejects_bad_id(tmp_path, bad):
    assert get_build(bad, str(tmp_path)) is None


def test_buildfile_size():
    assert BuildFile("a", "abc").size == 3
