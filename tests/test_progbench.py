"""Tests for the executable programming benchmark (scripts/benchmark/progbench.py).

Hermetic: no network. The only subprocess use is the harness's own sandbox,
which is exactly the unit under test. Grading is deterministic.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

SKRIPT = Path(__file__).resolve().parent.parent / "scripts" / "benchmark" / "progbench.py"


def _load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("progbench", SKRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["progbench"] = mod  # dataclasses resolve annotations via sys.modules
    spec.loader.exec_module(mod)
    return mod


pb = _load()


TWO_SUM_GOOD = (
    "def two_sum(nums, target):\n"
    "    seen = {}\n"
    "    for i, n in enumerate(nums):\n"
    "        if target - n in seen:\n"
    "            return sorted([seen[target - n], i])\n"
    "        seen[n] = i\n"
)
TWO_SUM_BAD = "def two_sum(nums, target):\n    return [0]\n"


def _task(task_id: str) -> "pb.Task":
    return next(t for t in pb.TASK_BANK if t.id == task_id)


# ── task bank integrity ──────────────────────────────────────────────────
def test_task_bank_has_all_three_kinds() -> None:
    kinds = {t.kind for t in pb.TASK_BANK}
    assert kinds == {"exec", "mutation", "keyword"}


def test_every_task_is_complete_for_its_kind() -> None:
    for t in pb.TASK_BANK:
        assert t.id and t.category and t.prompt
        if t.kind == "exec":
            assert t.tests.strip(), t.id
        elif t.kind == "mutation":
            assert t.reference.strip() and t.mutant.strip(), t.id
            assert t.reference != t.mutant, t.id
        elif t.kind == "keyword":
            assert t.checks and all(g for g in t.checks), t.id


def test_task_ids_are_unique() -> None:
    ids = [t.id for t in pb.TASK_BANK]
    assert len(ids) == len(set(ids))


def test_slugify_mutant_really_differs_from_reference() -> None:
    assert pb._SLUGIFY_MUTANT != pb._SLUGIFY_REF
    assert pb._SLUGIFY_MUTANT.count("_") == pb._SLUGIFY_REF.count("_") + 1


# ── extraction ───────────────────────────────────────────────────────────
def test_extract_python_prefers_the_last_fenced_block() -> None:
    text = "شرح\n```python\nfirst = 1\n```\nثم\n```python\nsecond = 2\n```"
    assert pb.extract_python(text) == "second = 2"


def test_extract_python_accepts_bare_fences() -> None:
    assert pb.extract_python("```\nx = 1\n```") == "x = 1"


def test_extract_python_falls_back_to_whole_text() -> None:
    assert pb.extract_python("def f():\n    return 1") == "def f():\n    return 1"


def test_extract_python_skips_empty_blocks() -> None:
    assert pb.extract_python("```python\n```\n```python\nz = 3\n```") == "z = 3"


def test_extract_python_handles_empty_string() -> None:
    assert pb.extract_python("") == ""


# ── exec grading ─────────────────────────────────────────────────────────
def test_grade_exec_passes_a_correct_solution() -> None:
    assert pb.grade_exec(TWO_SUM_GOOD, _task("gen_two_sum").tests)["ok"] is True


def test_grade_exec_fails_a_wrong_solution() -> None:
    res = pb.grade_exec(TWO_SUM_BAD, _task("gen_two_sum").tests)
    assert res["ok"] is False
    assert res["returncode"] != 0


def test_grade_exec_rejects_empty_code() -> None:
    res = pb.grade_exec("   ", _task("gen_two_sum").tests)
    assert res["ok"] is False and res["stderr"] == "EMPTY"


def test_grade_exec_times_out_on_an_infinite_loop() -> None:
    res = pb.grade_exec("while True:\n    pass\n", "assert True\n", timeout=1.0)
    assert res["ok"] is False and res["stderr"] == "TIMEOUT"


# ── mutation grading (test-writing quality) ──────────────────────────────
_STRONG_TESTS = (
    "from solution import slugify\n"
    "def test_space_and_case():\n"
    "    assert slugify('Hello World') == 'hello-world'\n"
    "def test_punctuation():\n"
    "    assert slugify('A_B c!') == 'a-b-c'\n"
)
_WEAK_TESTS = (
    "from solution import slugify\n"
    "def test_lowercase_only():\n"
    "    assert slugify('abc') == 'abc'\n"
)


def test_grade_mutation_accepts_discriminating_tests() -> None:
    res = pb.grade_mutation(_task("tests_slugify").reference,
                            _task("tests_slugify").mutant, _STRONG_TESTS)
    assert res["ok"] is True
    assert res["ref"] == (2, 0) and res["mut"] == (2, 2)


def test_grade_mutation_rejects_tests_that_miss_the_bug() -> None:
    res = pb.grade_mutation(_task("tests_slugify").reference,
                            _task("tests_slugify").mutant, _WEAK_TESTS)
    assert res["ok"] is False and res["mut"][1] == 0


def test_grade_mutation_rejects_empty_or_defless_code() -> None:
    assert pb.grade_mutation("x = 1", "x = 2", "   ")["reason"] == "EMPTY"
    assert pb.grade_mutation("x = 1", "x = 2", "assert True")["reason"] == "NO_TESTS"


def test_grade_mutation_reports_crash_when_tests_explode() -> None:
    boom = "def test_x():\n    pass\nraise RuntimeError('boom')\n"
    assert pb.grade_mutation("x = 1", "x = 2", boom)["reason"] == "CRASH"


# ── keyword grading ──────────────────────────────────────────────────────
def test_grade_keywords_requires_every_group() -> None:
    checks = (("sql injection", "حقن"), ("parameteriz", "prepared"))
    assert pb.grade_keywords("sql injection via parameterized query", checks)["ok"]
    assert not pb.grade_keywords("sql injection only", checks)["ok"]
    assert not pb.grade_keywords("use a firewall", checks)["ok"]


def test_grade_keywords_is_case_insensitive() -> None:
    assert pb.grade_keywords("SQL INJECTION; use PARAMETERIZED", (("injection",), ("parameteriz",)))["ok"]


# ── dispatch ─────────────────────────────────────────────────────────────
def test_grade_task_dispatches_by_kind() -> None:
    exec_res = pb.grade_task(_task("gen_two_sum"), f"```python\n{TWO_SUM_GOOD}\n```")
    assert exec_res["ok"] is True
    mut_res = pb.grade_task(_task("tests_slugify"), f"```python\n{_STRONG_TESTS}\n```")
    assert mut_res["ok"] is True
    kw = _task("review_sql_injection")
    assert pb.grade_task(kw, "SQL injection — use parameterized queries")["ok"] is True


def test_grade_task_unknown_kind_fails_closed() -> None:
    bogus = pb.Task(id="x", category="c", kind="weird", prompt="p")
    res = pb.grade_task(bogus, "anything")
    assert res["ok"] is False and res["reason"].startswith("UNKNOWN_KIND")


# ── SSE client (monkeypatched, no network) ───────────────────────────────
class _FakeResp:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def __iter__(self):  # noqa: ANN204 - mirrors http.client response
        return iter(self._lines)

    def read(self) -> bytes:
        return b"".join(self._lines)


def test_call_agent_parses_sse_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [
        b'data: {"type": "plan", "agent": "coder"}\n\n',
        b'data: {"type": "chunk", "content": "hello ", "provider": "groq_01"}\n\n',
        b'data: {"type": "chunk", "content": "world"}\n\n',
        b"data: [DONE]\n\n",
    ]
    monkeypatch.setattr(pb.urllib.request, "urlopen", lambda *a, **k: _FakeResp(lines))
    out = pb.call_agent("http://x", "coder", "hi")
    assert out["text"] == "hello world"
    assert out["provider"] == "groq_01" and out["error"] == ""


def test_call_agent_surfaces_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> object:
        raise OSError("connection refused")

    monkeypatch.setattr(pb.urllib.request, "urlopen", boom)
    out = pb.call_agent("http://x", None, "hi")
    assert out["text"] == "" and "connection refused" in out["error"]


def test_fetch_agents_reads_the_roster(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps({"agents": [{"id": "coder"}, {"id": "tester"}]}).encode()
    monkeypatch.setattr(pb.urllib.request, "urlopen", lambda *a, **k: _FakeResp([payload]))
    assert [a["id"] for a in pb.fetch_agents("http://x")] == ["coder", "tester"]


def test_fetch_agents_returns_empty_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pb.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert pb.fetch_agents("http://x") == []


# ── summary + report ─────────────────────────────────────────────────────
def _raw(rows: list[tuple[str, str, bool]]) -> dict:
    return {
        "base_url": "http://x", "duration": 1.0,
        "results": [
            {"agent": a, "task": t, "category": "c", "ok": ok}
            for a, t, ok in rows
        ],
    }


def test_summarize_computes_pass_at_1() -> None:
    summ = pb.summarize(_raw([("coder", "t1", True), ("coder", "t2", False),
                              ("tester", "t1", True), ("tester", "t2", True)]))
    assert summ["overall_pass_at_1"] == 0.75
    assert summ["per_agent"]["coder"]["pass_at_1"] == 0.5
    assert summ["per_agent"]["tester"]["pass_at_1"] == 1.0
    assert summ["per_task"]["t1"]["pass_at_1"] == 1.0


def test_summarize_handles_empty_results() -> None:
    summ = pb.summarize(_raw([]))
    assert summ["overall_pass_at_1"] == 0.0 and summ["total"] == 0


def test_render_markdown_contains_scores() -> None:
    raw = _raw([("coder", "gen_two_sum", True), ("coder", "tool_git_history", False)])
    md = pb.render_markdown(raw, pb.summarize(raw))
    assert "# مقاييس قدرات الوكلاء" in md
    assert "coder" in md and "gen_two_sum" in md and "50" in md


def test_bar_scales_between_empty_and_full() -> None:
    assert pb._bar(0.0) == "." * 16
    assert pb._bar(1.0) == "#" * 16
