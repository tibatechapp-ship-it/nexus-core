"""Tests for src.engineering.code_guardian — validation + auto-import repair."""

from __future__ import annotations

from src.engineering.code_guardian import CodeGuardian, GuardReport


def _g() -> CodeGuardian:
    return CodeGuardian()


# ── syntax ─────────────────────────────────────────────────────────

def test_empty_code_is_invalid() -> None:
    r = _g().analyze("   \n\n  ")
    assert not r.is_valid
    assert "Empty code" in r.errors[0]


def test_syntax_error_is_flagged() -> None:
    r = _g().analyze("def broken(:\n    pass\n")
    assert not r.is_valid
    assert r.needs_llm_fix is True
    assert any("SyntaxError" in e for e in r.errors)


def test_clean_code_passes() -> None:
    r = _g().analyze("def add(a, b):\n    return a + b\n\nprint(add(1, 2))\n")
    assert r.is_valid
    assert r.errors == []
    assert r.repaired_code is None


# ── undefined names ────────────────────────────────────────────────

def test_obviously_undefined_name_is_flagged() -> None:
    r = _g().analyze("def f():\n    return frobnicator(1)\n")
    assert not r.is_valid
    assert any("Undefined names" in e for e in r.errors)
    assert r.needs_llm_fix is True


# ── missing imports (auto-fixable) ─────────────────────────────────

def test_json_missing_import_is_auto_fixed() -> None:
    code = "def encode(x):\n    return dumps(x)\n"
    r = _g().analyze(code)
    assert r.is_valid
    assert r.repaired_code is not None
    assert "import json" in r.repaired_code
    assert "dumps(x)" in r.repaired_code


def test_os_missing_import_is_auto_fixed() -> None:
    code = "def here():\n    return getcwd()\n"
    r = _g().analyze(code)
    assert r.is_valid
    assert r.repaired_code is not None
    assert "import os" in r.repaired_code


def test_re_missing_import_is_auto_fixed() -> None:
    code = "def has_digit(s):\n    return bool(search(r'\\d', s))\n"
    r = _g().analyze(code)
    assert r.is_valid
    assert r.repaired_code is not None
    assert "import re" in r.repaired_code


def test_already_imported_no_double_fix() -> None:
    code = "import json\n\ndef encode(x):\n    return json.dumps(x)\n"
    r = _g().analyze(code)
    assert r.is_valid
    assert r.repaired_code is None


# ── mixed ──────────────────────────────────────────────────────────

def test_partial_fix_when_other_errors_remain() -> None:
    code = "def f():\n    return dumps(x) + frobnicator(2)\n"
    r = _g().analyze(code)
    assert not r.is_valid
    assert r.needs_llm_fix is True
    assert r.repaired_code is not None
    assert "import json" in r.repaired_code


# ── repair prompt ──────────────────────────────────────────────────

def test_repair_prompt_contains_error_and_code() -> None:
    g = _g()
    code = "def f():\n    return frobnicator(1)\n"
    r = g.analyze(code)
    prompt = g.generate_repair_prompt(code, r)
    assert "Errors:" in prompt
    assert "frobnicator" in prompt
    assert code.strip() in prompt


# ── to_dict ────────────────────────────────────────────────────────

def test_report_to_dict_round_trip() -> None:
    r = GuardReport(True, warnings=["x"], repaired_code="print(1)\n")
    d = r.to_dict()
    assert d["is_valid"] is True
    assert d["repaired_code"] == "print(1)\n"
    assert d["errors"] == []
