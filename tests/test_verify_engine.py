"""Unit tests for execution-based verification (``src/verify``).

Hermetic: the sandbox runner and the repair generator are always injected, so
no real code is executed and no network is touched. The two tests that DO use the
real ``exec_sandbox`` are guarded by ``requires_sandbox`` (the module is
gitignored, so it is absent on CI).
"""

from __future__ import annotations

import sys
import types

import pytest

from src.verify import engine as E
from src.verify import generators as G
from tests.conftest import requires_sandbox


class _Req:
    """Structural stand-in for ``exec_sandbox.ExecReq`` (pydantic-free)."""

    def __init__(self, language: str, code: str, stdin: str, timeout: int) -> None:
        self.language = language
        self.code = code
        self.stdin = stdin
        self.timeout = timeout


def _fake_sandbox(result: dict | None = None) -> types.ModuleType:
    """A drop-in ``exec_sandbox`` module whose ``_run`` returns a fixed dict."""
    mod = types.ModuleType("exec_sandbox")
    mod.LANGS = {"python": {"ext": ".py"}, "bash": {"ext": ".sh"}}
    mod.ALIASES = {"py": "python"}
    mod.MAX_TIMEOUT = 20
    mod.ExecReq = _Req
    mod._run = lambda lang, spec, req, t, t0: dict(
        result
        or {
            "language": lang,
            "verified": True,
            "ran": True,
            "timed_out": False,
            "exit_code": 0,
            "stdout": "ok",
            "stderr": "",
        }
    )
    return mod


@pytest.fixture()
def fake_sandbox(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    mod = _fake_sandbox()
    monkeypatch.setitem(sys.modules, "exec_sandbox", mod)
    return mod


def _runner(result: dict):
    """A runner callable that always answers with ``result``."""

    def run(code: str, language: str, stdin: str, timeout: int) -> dict:
        return dict(result)

    return run


# --------------------------------------------------------------------------- #
# compose_code
# --------------------------------------------------------------------------- #
def test_compose_code_without_tests_returns_body_only() -> None:
    assert E.compose_code("print(1)\n\n") == "print(1)"


def test_compose_code_appends_tests_for_python() -> None:
    out = E.compose_code("def f():\n    return 1", "assert f() == 1", "python")
    assert out == "def f():\n    return 1\n\nassert f() == 1"


def test_compose_code_rejects_tests_in_a_non_python_language() -> None:
    with pytest.raises(ValueError, match="بايثون"):
        E.compose_code("echo hi", "expect hi", "bash")


def test_compose_code_allows_a_non_python_language_without_tests() -> None:
    assert E.compose_code("echo hi\n", "", "bash") == "echo hi"


# --------------------------------------------------------------------------- #
# VerificationResult
# --------------------------------------------------------------------------- #
def test_result_to_dict_is_json_ready() -> None:
    res = E.VerificationResult(
        passed=True, reason="ok", code="x", language="python", attempts=1, detail=({"a": 1},)
    )
    assert res.to_dict() == {
        "passed": True,
        "reason": "ok",
        "code": "x",
        "language": "python",
        "attempts": 1,
        "detail": [{"a": 1}],
    }


# --------------------------------------------------------------------------- #
# sandbox availability + runner
# --------------------------------------------------------------------------- #
def test_sandbox_available_true_when_the_module_imports(fake_sandbox: types.ModuleType) -> None:
    assert E.sandbox_available() is True


def test_sandbox_available_false_when_the_module_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "exec_sandbox", None)
    assert E.sandbox_available() is False


def test_sandbox_runner_runs_through_the_module(fake_sandbox: types.ModuleType) -> None:
    out = E.sandbox_runner("print(1)", "py", "", 5)
    assert out["ran"] is True
    assert out["language"] == "python"  # the alias was resolved


def test_sandbox_runner_rejects_an_unknown_language(fake_sandbox: types.ModuleType) -> None:
    with pytest.raises(ValueError, match="غير مدعومة"):
        E.sandbox_runner("x", "ruby", "", 5)


@requires_sandbox
def test_sandbox_runner_executes_real_code() -> None:
    out = E.sandbox_runner("print(6 * 7)", "python", "", 10)
    assert out["ran"] is True
    assert out["exit_code"] == 0
    assert "42" in out["stdout"]


@requires_sandbox
def test_sandbox_runner_clamps_the_timeout_and_reports_syntax_errors() -> None:
    out = E.sandbox_runner("def broken(", "python", "", 999)
    assert out["verified"] is False
    assert "SyntaxError" in out["verify_error"]


# --------------------------------------------------------------------------- #
# verify_by_execution
# --------------------------------------------------------------------------- #
def test_verify_passes_on_a_clean_exit() -> None:
    res = E.verify_by_execution("print(1)", runner=_runner({"verified": True, "ran": True, "exit_code": 0}))
    assert res.passed is True
    assert res.reason == "ok"
    assert res.attempts == 1
    assert res.detail[0]["source"] == "print(1)"


def test_verify_reports_a_syntax_failure() -> None:
    res = E.verify_by_execution(
        "nope(", runner=_runner({"verified": False, "ran": False, "exit_code": None})
    )
    assert res.passed is False
    assert res.reason == "not-verified"


def test_verify_reports_a_code_that_never_ran() -> None:
    res = E.verify_by_execution(
        "x", runner=_runner({"verified": True, "ran": False, "exit_code": None})
    )
    assert res.reason == "did-not-run"


def test_verify_reports_a_timeout() -> None:
    res = E.verify_by_execution(
        "while 1: pass",
        runner=_runner({"verified": True, "ran": True, "timed_out": True, "exit_code": -9}),
    )
    assert res.reason == "timeout"


def test_verify_reports_an_unexpected_exit_code() -> None:
    res = E.verify_by_execution(
        "1/0",
        runner=_runner({"verified": True, "ran": True, "exit_code": 1, "stderr": "boom"}),
    )
    assert res.passed is False
    assert res.reason == "exit 1"
    assert res.detail[0]["stderr"] == "boom"


def test_verify_accepts_a_nonzero_expectation() -> None:
    res = E.verify_by_execution(
        "raise SystemExit(3)",
        expect_exit=3,
        runner=_runner({"verified": True, "ran": True, "exit_code": 3}),
    )
    assert res.passed is True


def test_verify_reports_a_runner_error_as_a_plain_failure() -> None:
    def boom(code: str, language: str, stdin: str, timeout: int) -> dict:
        raise RuntimeError("sandbox gone")

    res = E.verify_by_execution("print(1)", runner=boom)
    assert res.passed is False
    assert res.reason == "runner-error: sandbox gone"
    assert res.detail == ()


def test_verify_rejects_tests_in_a_non_python_language() -> None:
    res = E.verify_by_execution("echo hi", language="bash", tests="expect hi")
    assert res.passed is False
    assert res.reason.startswith("invalid-tests")


def test_verify_falls_back_to_the_real_runner_by_default(fake_sandbox: types.ModuleType) -> None:
    res = E.verify_by_execution("print(1)")
    assert res.passed is True
    assert res.detail[0]["stdout"] == "ok"


# --------------------------------------------------------------------------- #
# fix_loop
# --------------------------------------------------------------------------- #
_PASS = {"verified": True, "ran": True, "exit_code": 0}
_FAIL = {"verified": True, "ran": True, "exit_code": 1, "stderr": "boom"}


def test_fix_loop_passes_on_the_first_execution() -> None:
    res = E.fix_loop("task", "print(1)", runner=_runner(_PASS))
    assert res.passed is True
    assert res.attempts == 1


def test_fix_loop_repairs_and_passes() -> None:
    calls: list[str] = []

    def run(code: str, language: str, stdin: str, timeout: int) -> dict:
        calls.append(code)
        return dict(_PASS if "fixed" in code else _FAIL)

    res = E.fix_loop("t", "broken", max_attempts=3, runner=run, generate=lambda *a: "fixed()")
    assert res.passed is True
    assert res.attempts == 2
    assert res.code == "fixed()"
    assert len(calls) == 2


def test_fix_loop_without_a_generator_gives_up_after_one_run() -> None:
    res = E.fix_loop("t", "broken", runner=_runner(_FAIL))
    assert res.passed is False
    assert res.reason == "not-fixed"
    assert res.attempts == 1


def test_fix_loop_stops_when_the_repair_raises() -> None:
    def bad_generate(task: str, code: str, result: object, system: str) -> str:
        raise RuntimeError("provider down")

    res = E.fix_loop("t", "broken", runner=_runner(_FAIL), generate=bad_generate)
    assert res.passed is False
    assert res.attempts == 1
    assert res.detail[-1] == {"repair_error": "provider down"}


def test_fix_loop_stops_when_the_repair_is_empty() -> None:
    res = E.fix_loop("t", "broken", runner=_runner(_FAIL), generate=lambda *a: "   ")
    assert res.passed is False
    assert res.attempts == 1
    assert res.detail[-1]["exit_code"] == 1  # no repair_error appended


def test_fix_loop_stops_when_the_repair_is_not_a_string() -> None:
    def bad_generate(task: str, code: str, result: object, system: str) -> int:
        return 42

    res = E.fix_loop("t", "broken", runner=_runner(_FAIL), generate=bad_generate)  # type: ignore[arg-type]
    assert res.attempts == 1


def test_fix_loop_clamps_the_attempt_budget() -> None:
    seen: list[str] = []

    def run(code: str, language: str, stdin: str, timeout: int) -> dict:
        seen.append(code)
        return dict(_FAIL)

    res = E.fix_loop(
        "t", "a", max_attempts=99, runner=run, generate=lambda task, code, result, system: code + "a"
    )
    assert res.attempts == E.MAX_ATTEMPTS
    assert len(seen) == E.MAX_ATTEMPTS


def test_fix_loop_treats_zero_attempts_as_one() -> None:
    res = E.fix_loop("t", "broken", max_attempts=0, runner=_runner(_FAIL))
    assert res.attempts == 1


# --------------------------------------------------------------------------- #
# generators
# --------------------------------------------------------------------------- #
def test_extract_code_pulls_the_last_fenced_block() -> None:
    text = "first:\n```python\nprint(1)\n```\nand better:\n```python\nprint(2)\n```\n"
    assert G.extract_code(text) == "print(2)"


def test_extract_code_falls_back_to_the_whole_text() -> None:
    assert G.extract_code("  print(1)  ") == "print(1)"


def test_extract_code_handles_empty_input() -> None:
    assert G.extract_code("") == ""


def test_build_fix_prompt_includes_task_reason_and_error() -> None:
    res = E.VerificationResult(
        passed=False,
        reason="exit 1",
        code="x",
        language="python",
        attempts=1,
        detail=({"stderr": "NameError: x"},),
    )
    prompt = G.build_fix_prompt("print x", "x", res)
    assert "print x" in prompt
    assert "exit 1" in prompt
    assert "NameError: x" in prompt
    assert "```" in prompt


def test_build_fix_prompt_handles_a_result_without_error_output() -> None:
    res = E.VerificationResult(False, "did-not-run", "x", "python", 1, ())
    assert G._NO_OUTPUT in G.build_fix_prompt("t", "x", res)


def test_error_text_prefers_stderr_then_verify_error_then_stdout() -> None:
    res = E.VerificationResult(False, "exit 1", "x", "python", 1, ({"stdout": "out"},))
    assert G._error_text(res) == "out"
    res2 = E.VerificationResult(False, "x", "x", "python", 1, ({"verify_error": "bad"},))
    assert G._error_text(res2) == "bad"


def test_error_text_is_empty_for_a_missing_or_non_dict_detail() -> None:
    assert G._error_text(E.VerificationResult(False, "x", "x", "python", 1, ())) == ""
    assert G._error_text(E.VerificationResult(False, "x", "x", "python", 1, ("nope",))) == ""


def test_llm_generate_unwraps_a_router_dict() -> None:
    class FakeRouter:
        def generate(self, prompt: str, system: str = "", role: str = "fast") -> dict:
            assert "أصلح" in prompt
            assert system == "SYS"
            return {"ok": True, "text": "```\nprint(1)\n```"}

    out = G.llm_generate("t", "x", _pass_result(), "SYS", router=FakeRouter())
    assert G.extract_code(out) == "print(1)"


def test_llm_generate_returns_empty_when_the_router_gives_no_text() -> None:
    class SilentRouter:
        def generate(self, prompt: str, system: str = "", role: str = "fast") -> dict:
            return {"ok": False, "text": ""}

    assert G.llm_generate("t", "x", _pass_result(), router=SilentRouter()) == ""


def test_llm_generate_wraps_a_plain_string_reply() -> None:
    class StringRouter:
        def generate(self, prompt: str, system: str = "", role: str = "fast") -> str:
            return "print(1)"

    assert G.llm_generate("t", "x", _pass_result(), router=StringRouter()) == "print(1)"


def test_llm_generate_swallows_a_broken_router() -> None:
    class BoomRouter:
        def generate(self, prompt: str, system: str = "", role: str = "fast") -> dict:
            raise RuntimeError("no provider")

    assert G.llm_generate("t", "x", _pass_result(), router=BoomRouter()) == ""


def test_llm_generate_builds_the_default_router_lazily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import novamind.core.llm_router as lr

    class StubRouter:
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, prompt: str, system: str = "", role: str = "fast") -> dict:
            self.calls += 1
            return {"ok": True, "text": "repaired"}

    monkeypatch.setattr(lr, "LLMRouter", StubRouter, raising=False)
    assert G.llm_generate("t", "x", _pass_result()) == "repaired"


def _pass_result() -> E.VerificationResult:
    return E.VerificationResult(True, "ok", "x", "python", 1, ({"stdout": "ok"},))


def test_llm_generate_returns_empty_on_a_none_reply() -> None:
    class NoneRouter:
        def generate(self, prompt: str, system: str = "", role: str = "fast") -> None:
            return None

    assert G.llm_generate("t", "x", _pass_result(), router=NoneRouter()) == ""
