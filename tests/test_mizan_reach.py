"""س2 regression tests — import-level reachability (docs/MIZAN_ROADMAP.md).

Gap closed: Snyk-class engines downgrade dependency findings the code never
reaches; MIZAN now answers with a declared-scope tri-state verdict
(``reachable`` / ``import-only`` / ``absent``) over a direct-import graph.
These tests pin the verdict semantics, the conservative upward bias
(dynamic import ⇒ reachable), the pip-name approximation, the honesty
counters (unparsed files are counted, not hidden) and the CLI.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from src.mizan.reachability import (
    ABSENT,
    IMPORT_ONLY,
    REACHABLE,
    ImportFacts,
    assess_tree,
    import_roots_for,
    iter_py_files,
)

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "mizan" / "mizan_reach.py"
_FIX_SCRIPT = _ROOT / "scripts" / "mizan" / "mizan_fix.py"


def _write_tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


# ── verdict semantics ────────────────────────────────────────────────────────


def test_verdict_reachable_when_call_resolves(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "app.py": "import requests\n\ndef go():\n    return requests.get('x')\n",
    })
    facts = assess_tree(tmp_path, ["requests"]).facts["requests"]
    assert facts.verdict == REACHABLE
    assert facts.files_importing == ("app.py",)
    assert facts.call_files == ("app.py",)
    assert not facts.dynamic_import


def test_verdict_import_only_when_never_called(tmp_path: Path) -> None:
    _write_tree(tmp_path, {"lazy.py": "import flask\n"})
    facts = assess_tree(tmp_path, ["flask"]).facts["flask"]
    assert facts.verdict == IMPORT_ONLY
    assert facts.files_importing == ("lazy.py",)
    assert facts.call_files == ()


def test_verdict_absent_when_no_import(tmp_path: Path) -> None:
    _write_tree(tmp_path, {"app.py": "x = 1\n"})
    assert assess_tree(tmp_path, ["neverpkg"]).facts["neverpkg"].verdict == ABSENT


def test_from_import_with_alias_call(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "app.py": "from requests import get as fetch\n\ndef go():\n    return fetch('x')\n",
    })
    assert assess_tree(tmp_path, ["requests"]).facts["requests"].verdict == REACHABLE


def test_submodule_import_and_dotted_call(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "app.py": "import requests.sessions\n\ndef go():\n"
                  "    return requests.sessions.Session()\n",
    })
    assert assess_tree(tmp_path, ["requests"]).facts["requests"].verdict == REACHABLE


def test_dynamic_import_is_conservatively_reachable(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "app.py": "mod = __import__('requests')\n",
        "other.py": "import importlib\nmod2 = importlib.import_module('requests')\n",
    })
    facts = assess_tree(tmp_path, ["requests"]).facts["requests"]
    assert facts.dynamic_import
    assert facts.verdict == REACHABLE


def test_dash_to_underscore_candidate(tmp_path: Path) -> None:
    _write_tree(tmp_path, {"app.py": "import my_pkg\n\n\ndef go() -> None:\n"
                          "    my_pkg.run()\n"})
    # pip name "my-pkg" → import candidate "my_pkg"
    assert assess_tree(tmp_path, ["my-pkg"]).facts["my-pkg"].verdict == REACHABLE


def test_relative_imports_never_count_as_dependency(tmp_path: Path) -> None:
    _write_tree(tmp_path, {"app.py": "from .helpers import x\nfrom .. import y\n"})
    assert assess_tree(tmp_path, ["helpers"]).facts["helpers"].verdict == ABSENT


def test_unparsed_files_are_counted_not_hidden(tmp_path: Path) -> None:
    _write_tree(tmp_path, {"broken.py": "def f(:\n", "ok.py": "x = 1\n"})
    res = assess_tree(tmp_path, ["requests"])
    assert res.unparsed == 1
    assert res.files_scanned == 1


def test_skip_dirs_not_walked(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        ".venv/lib/site.py": "import requests\n",
        "__pycache__/c.py": "import requests\n",
        "src.py": "x = 1\n",
    })
    res = assess_tree(tmp_path, ["requests"])
    assert res.files_scanned == 1  # only src.py


def test_iter_py_files_single_file_input(tmp_path: Path) -> None:
    f = _write_tree(tmp_path, {"a.py": "x = 1\n"})
    assert iter_py_files(f / "a.py") == [f / "a.py"]
    assert iter_py_files(f / "a.txt") == []


# ── unit helpers ─────────────────────────────────────────────────────────────


def test_import_roots_for_extracts_roots_and_dynamic() -> None:
    import ast

    tree = ast.parse(
        "import a.b as ab\nfrom c.d import e\nfrom .rel import f\n"
        "g = __import__('h')\n",
    )
    roots, dotted, dynamic = import_roots_for(tree)
    assert roots == {"a", "c"}  # dynamic literals are checked separately
    assert {"a.b", "c.d"} <= dotted
    assert dynamic


def test_import_facts_verdict_default_absent() -> None:
    assert ImportFacts(package="x").verdict == ABSENT


def test_assessment_verdicts_sorted() -> None:
    from src.mizan.reachability import Assessment

    assert assess_tree(Path("."), []).verdicts() == {}
    # build one manually for the sorted mapping contract
    facts = {"b": ImportFacts(package="b"), "a": ImportFacts(package="a")}
    assert Assessment(facts=facts).verdicts() == {"a": ABSENT, "b": ABSENT}


# ── CLI ──────────────────────────────────────────────────────────────────────


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, timeout=120,
    )


def test_cli_packages_and_json(tmp_path: Path) -> None:
    _write_tree(tmp_path / "tree", {
        "app.py": "import requests\nrequests.get('x')\n",
    })
    out = tmp_path / "verdicts.json"
    proc = _run_cli(str(tmp_path / "tree"), "--packages", "requests,flask",
                    "--json", str(out))
    assert proc.returncode == 0, proc.stderr
    assert "reachable" in proc.stdout
    assert "absent" in proc.stdout
    assert "حدود معلنة" in proc.stdout  # declared-limitation note for absent
    payload = out.read_text(encoding="utf-8")
    assert '"verdict": "reachable"' in payload


def test_cli_manifest_source(tmp_path: Path) -> None:
    tree = _write_tree(tmp_path / "tree", {"app.py": "import flask\n"})
    (tmp_path / "requirements.txt").write_text("flask>=1.0\n", encoding="utf-8")
    proc = _run_cli(str(tree), "--manifest", str(tmp_path / "requirements.txt"))
    assert proc.returncode == 0
    assert "import-only" in proc.stdout


def test_cli_errors(tmp_path: Path) -> None:
    proc = _run_cli(str(tmp_path / "missing"), "--packages", "a")
    assert proc.returncode == 1
    proc = _run_cli(str(tmp_path), "--manifest", str(tmp_path / "nope.txt"))
    assert proc.returncode == 1


# ── س1 integration: the fixer downgrades absent, never drops ────────────────


def test_fix_cli_reachability_flag_downgrades_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--reachability annotates verdicts; absent plans stay planned."""
    import json as _json

    monkeypatch.chdir(tmp_path)
    (tmp_path / "requirements.txt").write_text("requests>=1.2\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")  # no import
    advfile = tmp_path / "adv.json"
    advfile.write_text(_json.dumps({"advisories": [
        {"package": "requests", "vulnerable": "<1.9", "fixed": "1.9",
         "ids": ["GHSA-1"], "severity": "HIGH"},
    ]}), encoding="utf-8")
    report = tmp_path / "rep.md"
    proc = subprocess.run(
        [sys.executable, str(_FIX_SCRIPT), "requirements.txt",
         "--advisories", str(advfile), "--reachability", "--report-md", str(report)],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 2  # still actionable — downgraded, not dropped
    assert "reach=absent" in proc.stdout
    text = report.read_text(encoding="utf-8")
    assert "absent" in text and "أولوية مخفضة" in text
    # the fix itself is still planned byte-exactly
    assert "`==1.9`" in text
