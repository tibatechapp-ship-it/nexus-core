from __future__ import annotations

import novamind.core.analysis.error_detector as module
from novamind.core.analysis.error_detector import ErrorDetector


def test_regex_scan_reports_python_security_and_style_findings():
    code = "value = eval(user_input)\nif value == None:\n    pass\n"
    findings = ErrorDetector.regex_scan(code, "python")

    assert {item["type"] for item in findings} >= {"SecurityRisk", "CompareNone"}
    assert all(item["layer"] == "L1-regex" for item in findings)
    assert all(item["line"] > 0 for item in findings)


def test_regex_scan_skips_comment_lines_and_unknown_language():
    assert ErrorDetector.regex_scan("# eval(x)\n// eval(x)", "python") == []
    assert ErrorDetector.regex_scan("eval(x)", "unknown") == []


def test_ast_scan_reports_syntax_error_without_raising():
    findings = ErrorDetector.ast_scan("def broken(:\n    pass")
    assert len(findings) == 1
    assert findings[0]["type"] == "SyntaxError"
    assert findings[0]["severity"] == "error"


def test_ast_scan_detects_unused_import_mutable_default_and_long_function():
    body = "\n".join(f"    value_{i} = {i}" for i in range(55))
    code = "import os\ndef work(items=[]):\n" + body + "\n    return 1\n"
    findings = ErrorDetector.ast_scan(code)
    kinds = {item["type"] for item in findings}

    assert "UnusedImport" in kinds
    assert "MutableDefault" in kinds
    assert "LongFunction" in kinds


def test_ast_scan_detects_too_many_arguments():
    findings = ErrorDetector.ast_scan("def f(a, b, c, d, e, f):\n    return a\n")
    assert any(item["type"] == "TooManyArgs" for item in findings)


def test_import_check_reports_missing_import(monkeypatch):
    monkeypatch.setattr(ErrorDetector, "_module_available", staticmethod(lambda name: False))
    findings = ErrorDetector.import_check("import definitely_missing_package\n")
    assert len(findings) == 1
    assert findings[0]["type"] == "MissingImport"
    assert findings[0]["severity"] == "error"


def test_import_check_ignores_known_stdlib_and_invalid_python():
    assert ErrorDetector.import_check("import os\nfrom pathlib import Path\n") == []
    assert ErrorDetector.import_check("import (") == []


def test_unused_vars_detects_unread_assignment_but_ignores_private_name():
    findings = ErrorDetector.unused_vars(
        "def f():\n    unused = 1\n    _internal = 2\n    return 3\n"
    )
    assert len(findings) == 1
    assert findings[0]["type"] == "UnusedVariable"
    assert "'unused'" in findings[0]["message"]


def test_complexity_detects_branch_heavy_function():
    code = "def f(x):\n" + "".join(
        f"    if x == {i}:\n        x += 1\n" for i in range(11)
    ) + "    return x\n"
    findings = ErrorDetector.complexity(code)
    assert len(findings) == 1
    assert findings[0]["type"] == "HighComplexity"


def test_detect_aggregates_python_layers_and_language_from_extension(monkeypatch):
    monkeypatch.setattr(ErrorDetector, "_module_available", staticmethod(lambda name: True))
    result = ErrorDetector.detect(
        "import os\ndef f():\n    return eval('1')\n",
        filename="sample.py",
    )

    assert result["language"] == "python"
    assert result["file"] == "sample.py"
    assert result["total"] >= 1
    assert set(result["by_severity"]) == {"error", "warning", "note"}
    assert any(item["layer"] == "L1-regex" for item in result["issues"])
    assert result["ok"] is False


def test_detect_supports_javascript_and_typescript_without_python_ast_layers():
    js = ErrorDetector.detect("var value = 1;\nconsole.log(value);", "sample.js")
    ts = ErrorDetector.detect("const value: any = 1;", "sample.ts")

    assert js["language"] == "javascript"
    assert any(item["type"] == "StyleWarning" for item in js["issues"])
    assert all(item["layer"] == "L1-regex" for item in js["issues"])
    assert ts["language"] == "typescript"
    assert any(item["type"] == "TypeWarning" for item in ts["issues"])


def test_severity_mapping_is_stable():
    assert ErrorDetector._severity("SecurityRisk") == "error"
    assert ErrorDetector._severity("MutableDefault") == "warning"
    assert ErrorDetector._severity("Note") == "note"
