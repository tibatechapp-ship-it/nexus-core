"""س6 regression tests — the MIZAN rules DSL (docs/MIZAN_ROADMAP.md).

Gap closed: Semgrep lets teams write their own patterns; MIZAN was
read-only over its built-ins. These tests pin the declared scope: JSON
rules over ``ast`` (node whitelist + dotted pattern + flat regex), strict
validation (unknown node/severity/regex are load errors, not no-ops), the
shipped reviewed built-ins, and the س6 exit gate — a ~10-line custom rule
catching a pattern the built-ins miss.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.mizan.rules import (
    SCHEMA,
    Rule,
    RulesError,
    builtin_rules,
    builtin_rules_path,
    check_path,
    load_rules,
)

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "mizan" / "mizan_rules.py"


def _rules_file(tmp_path: Path, rules: list[dict]) -> Path:
    p = tmp_path / "rules.json"
    p.write_text(
        json.dumps({"schema": SCHEMA, "rules": rules}, ensure_ascii=False),
        encoding="utf-8",
    )
    return p


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


# ── the س6 exit gate: a 10-line custom rule catches what built-ins miss ──────


def test_custom_rule_catches_builtin_blind_spot(tmp_path: Path) -> None:
    tree = _tree(tmp_path, {
        "app.py": "import curl_html\n\n\ndef fetch(url: str) -> str:\n"
                  "    return curl_html.grab(url)\n",
    })
    # built-ins: nothing matches curl_html
    base, _, _ = check_path(tree, builtin_rules())
    assert base == []
    # the 10-line custom rule
    rules = _rules_file(tmp_path, [{
        "id": "TEAM-001",
        "match": {"node": "Call", "pattern": "curl_html.grab"},
        "severity": "MEDIUM",
        "message": "curl_html مكتبة مهجورة بثغرات معلومة — استخدم requests.",
        "fix-hint": "استبدل بـ requests.get.",
    }])
    findings, scanned, unparsed = check_path(tree, load_rules(rules))
    assert scanned == 1 and unparsed == 0
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "TEAM-001"
    assert f.path == "app.py"
    assert f.line == 5
    assert "curl_html.grab" in f.snippet


# ── matching semantics ───────────────────────────────────────────────────────


def test_node_type_only_rule_matches_any(tmp_path: Path) -> None:
    tree = _tree(tmp_path, {"a.py": "del_item()\nother()\n"})
    rules = _rules_file(tmp_path, [{
        "id": "ANY-CALL", "match": {"node": "Call"},
        "severity": "LOW", "message": "any call",
    }])
    findings, _, _ = check_path(tree, load_rules(rules))
    assert {f.line for f in findings} == {1, 2}


def test_suffix_pattern_matches_submodules(tmp_path: Path) -> None:
    tree = _tree(tmp_path, {"a.py": "import os\nos.system('ls')\n"})
    rules = _rules_file(tmp_path, [{
        "id": "S1", "match": {"node": "Call", "pattern": "system"},
        "severity": "HIGH", "message": "shell out",
    }])
    findings, _, _ = check_path(tree, load_rules(rules))
    assert [f.line for f in findings] == [2]


def test_regex_filters_matches(tmp_path: Path) -> None:
    tree = _tree(tmp_path, {
        "a.py": "import subprocess\nsubprocess.Popen('ls', shell=True)\n"
                "subprocess.Popen(['ls'])\n",
    })
    rules = _rules_file(tmp_path, [{
        "id": "R1", "match": {"node": "Call", "pattern": "subprocess.Popen",
                              "regex": "shell[ ]*=[ ]*True"},
        "severity": "HIGH", "message": "shell mode",
    }])
    findings, _, _ = check_path(tree, load_rules(rules))
    assert [f.line for f in findings] == [2]


def test_import_rule_matches_module_names(tmp_path: Path) -> None:
    tree = _tree(tmp_path, {"a.py": "import legacy_bad\nfrom x import y\n"})
    rules = _rules_file(tmp_path, [{
        "id": "IMP", "match": {"node": "Import", "pattern": "legacy_bad"},
        "severity": "MEDIUM", "message": "banned import",
    }])
    findings, _, _ = check_path(tree, load_rules(rules))
    assert [f.line for f in findings] == [1]


def test_unparseable_files_counted(tmp_path: Path) -> None:
    tree = _tree(tmp_path, {"broken.py": "def (:\n", "ok.py": "x = 1\n"})
    rules = _rules_file(tmp_path, [{
        "id": "A", "match": {"node": "Name"}, "severity": "LOW",
        "message": "m",
    }])
    _, scanned, unparsed = check_path(tree, load_rules(rules))
    assert scanned == 1 and unparsed == 1


# ── validation is strict (no silent no-ops) ──────────────────────────────────


def test_unknown_node_is_load_error(tmp_path: Path) -> None:
    rules = _rules_file(tmp_path, [{
        "id": "X", "match": {"node": "NotANode"}, "severity": "LOW",
        "message": "m",
    }])
    with pytest.raises(RulesError, match="whitelist"):
        load_rules(rules)


def test_unknown_severity_is_load_error(tmp_path: Path) -> None:
    rules = _rules_file(tmp_path, [{
        "id": "X", "match": {"node": "Call"}, "severity": "EXTREME",
        "message": "m",
    }])
    with pytest.raises(RulesError, match="severity"):
        load_rules(rules)


def test_missing_fields_are_load_errors(tmp_path: Path) -> None:
    with pytest.raises(RulesError, match="missing 'id'"):
        load_rules(_rules_file(tmp_path, [
            {"match": {"node": "Call"}, "severity": "LOW", "message": "m"},
        ]))
    with pytest.raises(RulesError, match="match"):
        load_rules(_rules_file(tmp_path, [
            {"id": "X", "severity": "LOW", "message": "m"},
        ]))
    with pytest.raises(RulesError, match="message"):
        load_rules(_rules_file(tmp_path, [
            {"id": "X", "match": {"node": "Call"}, "severity": "LOW"},
        ]))


def test_bad_regex_is_load_error(tmp_path: Path) -> None:
    rules = _rules_file(tmp_path, [{
        "id": "X", "match": {"node": "Call", "regex": "(unclosed"},
        "severity": "LOW", "message": "m",
    }])
    with pytest.raises(RulesError, match="bad rule regex"):
        load_rules(rules)


def test_nested_quantifier_regex_rejected(tmp_path: Path) -> None:
    rules = _rules_file(tmp_path, [{
        "id": "X", "match": {"node": "Call", "regex": "(a+)+$"},
        "severity": "LOW", "message": "m",
    }])
    with pytest.raises(RulesError, match="ReDoS"):
        load_rules(rules)


def test_wrong_schema_rejected(tmp_path: Path) -> None:
    p = tmp_path / "w.json"
    p.write_text('{"schema": "other/9", "rules": []}', encoding="utf-8")
    with pytest.raises(RulesError, match="unsupported schema"):
        load_rules(p)
    p.write_text("[]", encoding="utf-8")
    with pytest.raises(RulesError, match="object"):
        load_rules(p)
    p.write_text('{"schema": "mizan.rules/1"}', encoding="utf-8")
    with pytest.raises(RulesError, match="rules"):
        load_rules(p)
    p.write_text('{"schema": "mizan.rules/1", "rules": [1]}', encoding="utf-8")
    with pytest.raises(RulesError, match="#0"):
        load_rules(p)


def test_unreadable_file_is_load_error(tmp_path: Path) -> None:
    with pytest.raises(RulesError, match="cannot read"):
        load_rules(tmp_path / "missing.json")


# ── shipped built-ins ────────────────────────────────────────────────────────


def test_builtin_rules_load_and_cover() -> None:
    rules = builtin_rules()
    assert len(rules) >= 5
    ids = {r.id for r in rules}
    assert "MIZ-EVAL" in ids and "MIZ-SYSTEM" in ids
    assert builtin_rules_path().exists()


def test_builtin_rules_fire_on_fixture(tmp_path: Path) -> None:
    tree = _tree(tmp_path, {
        "bad.py": "import os\nimport pickle\nimport yaml\n\n"
                  "eval('1+1')\nexec('2')\nos.system('ls')\n"
                  "pickle.loads(b'')\nyaml.load(d, Loader=yaml.Loader)\n",
    })
    findings, _, _ = check_path(tree, builtin_rules())
    ids = {f.rule_id for f in findings}
    assert {"MIZ-EVAL", "MIZ-EXEC", "MIZ-SYSTEM", "MIZ-PICKLE",
            "MIZ-YAML-LOAD"} <= ids


def test_rule_dataclass_shape() -> None:
    r = Rule(id="T", node="Call", pattern="", regex=None,
             severity="LOW", message="m", fix_hint="")
    assert r.pattern == ""


# ── CLI ──────────────────────────────────────────────────────────────────────


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, timeout=120,
    )


def test_cli_check_finds_and_exits_2(tmp_path: Path) -> None:
    tree = _tree(tmp_path / "tree", {"app.py": "eval('1')\n"})
    out = tmp_path / "f.json"
    proc = _run_cli("check", "--json", str(out), str(tree))
    assert proc.returncode == 2, proc.stderr
    assert "MIZ-EVAL" in proc.stdout
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["findings"][0]["rule_id"] == "MIZ-EVAL"


def test_cli_check_custom_rules_file(tmp_path: Path) -> None:
    tree = _tree(tmp_path / "tree", {"app.py": "curl_html.grab('u')\n"})
    rules = _rules_file(tmp_path, [{
        "id": "T1", "match": {"node": "Call", "pattern": "curl_html.grab"},
        "severity": "MEDIUM", "message": "m",
    }])
    proc = _run_cli("check", "--no-builtin", "--rules", str(rules), str(tree))
    assert proc.returncode == 2
    assert "T1" in proc.stdout


def test_cli_check_clean_exit_0(tmp_path: Path) -> None:
    tree = _tree(tmp_path / "tree", {"app.py": "x = 1\n"})
    proc = _run_cli("check", str(tree))
    assert proc.returncode == 0
    assert "clean" in proc.stdout


def test_cli_validate(tmp_path: Path) -> None:
    rules = _rules_file(tmp_path, [{
        "id": "V1", "match": {"node": "Call", "pattern": "eval"},
        "severity": "HIGH", "message": "m", "fix-hint": "hint",
    }])
    proc = _run_cli("validate", str(rules))
    assert proc.returncode == 0
    assert "V1" in proc.stdout and "pattern=eval" in proc.stdout
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema": "mizan.rules/1", "rules": [{"id": "Z"}]}',
                   encoding="utf-8")
    proc = _run_cli("validate", str(bad))
    assert proc.returncode == 1


def test_cli_missing_path_exit_1(tmp_path: Path) -> None:
    proc = _run_cli("check", str(tmp_path / "missing"))
    assert proc.returncode == 1
