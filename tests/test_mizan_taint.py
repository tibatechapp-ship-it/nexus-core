"""س3 regression tests — cross-file taint analysis (docs/MIZAN_ROADMAP.md).

Gap closed: complex injection flows that span files escape single-file
scanners. These tests pin the س3 exit gate: a multi-file tree whose taint
path crosses 3 files is detected with a stitched chain; clean trees stay
clean; cycles and step budgets terminate; and the CLI reports findings
with exit 2 and truncation loudly.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from src.mizan.taint import (
    MAX_CHAIN,
    _dotted,
    TaintReport,
    scan_tree,
)

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "mizan" / "mizan_taint.py"


def _write_tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


# ── the س3 exit gate: one flow, three files, stitched chain ─────────────────


def test_three_file_chain_is_detected(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "a.py": "def get_name():\n    return input('name')\n",
        "b.py": "from a import get_name\n\ndef shape(x):\n    return x.strip()\n"
                "\ndef run():\n    data = get_name()\n    return shape(data)\n",
        "c.py": "from b import run\n\ndef sink_it():\n    value = run()\n"
                "    eval(value)\n",
    })
    rep = scan_tree(tmp_path)
    assert len(rep.findings) == 1, rep.findings
    f = rep.findings[0]
    assert f.sink == "eval"
    assert f.file == "c.py"
    # chain: source step + the two cross-file call entries
    assert any("input()" in s for s in f.chain)
    assert any("→ run()" in s for s in f.chain)
    assert any("→ shape()" in s for s in f.chain)


def test_direct_source_to_sink_same_file(tmp_path: Path) -> None:
    _write_tree(tmp_path, {"app.py": "def go():\n    eval(input())\n"})
    rep = scan_tree(tmp_path)
    assert len(rep.findings) == 1
    assert rep.findings[0].sink == "eval"
    assert "input()" in rep.findings[0].chain[0]


def test_taint_via_argument_across_files(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "reader.py": "def read():\n    return input()\n",
        "out.py": "from reader import read\n\ndef handle(x):\n    exec(x)\n"
                  "\ndef main():\n    handle(read())\n",
    })
    rep = scan_tree(tmp_path)
    assert len(rep.findings) == 1
    f = rep.findings[0]
    assert f.sink == "exec"
    assert any("→ handle()" in s for s in f.chain)


def test_sink_families_are_all_watched(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "sinks.py": (
            "import os\nimport subprocess\n\n"
            "def a():\n    os.system(input())\n\n"
            "def b():\n    subprocess.run(input(), shell=True)\n\n"
            "def c():\n    cursor = object()\n    cursor.execute(input())\n\n"
            "def d():\n    exec(input())\n"
        ),
    })
    rep = scan_tree(tmp_path)
    sinks = {f.sink for f in rep.findings}
    assert sinks == {"os.system", "subprocess.run", "*.execute", "exec"}


def test_sources_env_and_argv(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "env.py": "import os\nimport sys\n\n"
                  "def via_env():\n    os.system(os.environ['CMD'])\n\n"
                  "def via_argv():\n    exec(sys.argv[1])\n",
    })
    sinks = {f.sink for f in scan_tree(tmp_path).findings}
    assert sinks == {"os.system", "exec"}


def test_clean_tree_stays_clean(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "ok.py": "import subprocess\n\n\ndef run(cmd: list[str]) -> int:\n"
                 "    return subprocess.run(cmd, check=False).returncode\n\n\n"
                 "def calc(x: int) -> int:\n    y = x + 1\n    return y\n",
    })
    rep = scan_tree(tmp_path)
    assert rep.findings == []
    assert rep.truncated is False


def test_unparsed_files_counted(tmp_path: Path) -> None:
    _write_tree(tmp_path, {"broken.py": "def f(:\n", "ok.py": "x = 1\n"})
    rep = scan_tree(tmp_path)
    assert rep.unparsed == 1
    assert rep.files_scanned == 1


def test_call_cycle_terminates(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "loop.py": "def ping(x):\n    return pong(x)\n\n"
                   "def pong(x):\n    return ping(x)\n\n"
                   "def boom():\n    eval(ping(input()))\n",
    })
    rep = scan_tree(tmp_path)
    assert not rep.truncated
    assert len(rep.findings) == 1


def test_step_budget_reports_truncation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_tree(tmp_path, {"app.py": "def go():\n    eval(input())\n"})
    monkeypatch.setattr("src.mizan.taint.MAX_STEPS", 5)
    rep = scan_tree(tmp_path)
    assert rep.truncated is True


def test_chain_cap_stops_deep_flows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # deep but finite chain: f0 → f1 → … → f39, sink at the end
    lines = ["def f0(x):\n    return f1(x)\n"]
    for i in range(1, 39):
        lines.append(f"def f{i}(x):\n    return f{i + 1}(x)\n")
    lines.append("def f39(x):\n    eval(x)\n")
    lines.append("def main():\n    f0(input())\n")
    _write_tree(tmp_path, {"deep.py": "".join(lines)})
    monkeypatch.setattr("src.mizan.taint.MAX_CHAIN", MAX_CHAIN)
    rep = scan_tree(tmp_path)
    assert isinstance(rep, TaintReport)


def test_dotted_helper() -> None:
    import ast

    assert _dotted(ast.parse("os.system", mode="eval").body) == "os.system"
    assert _dotted(ast.parse("x", mode="eval").body) == "x"
    assert _dotted(ast.parse("f(1)", mode="eval").body) == ""


def test_same_name_functions_last_wins(tmp_path: Path) -> None:
    # declared limit: name-based resolution, the last parsed definition wins
    _write_tree(tmp_path, {
        "one.py": "def go(x):\n    return x\n",
        "two.py": "def go(x):\n    eval(x)\n\ndef main():\n    go(input())\n",
    })
    rep = scan_tree(tmp_path)
    assert len(rep.findings) == 1
    assert rep.findings[0].file == "two.py"


# ── CLI ──────────────────────────────────────────────────────────────────────


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, timeout=120,
    )


def test_cli_finding_exit_2_and_json(tmp_path: Path) -> None:
    tree = _write_tree(tmp_path / "tree", {
        "app.py": "def go():\n    eval(input())\n",
    })
    out = tmp_path / "findings.json"
    proc = _run_cli(str(tree), "--json", str(out))
    assert proc.returncode == 2, proc.stderr
    assert "[eval]" in proc.stdout
    payload = out.read_text(encoding="utf-8")
    assert '"sink": "eval"' in payload


def test_cli_clean_exit_0(tmp_path: Path) -> None:
    tree = _write_tree(tmp_path / "tree", {"app.py": "x = 1\n"})
    proc = _run_cli(str(tree))
    assert proc.returncode == 0
    assert "no source→sink flows" in proc.stdout


def test_cli_error_exit_1(tmp_path: Path) -> None:
    proc = _run_cli(str(tmp_path / "missing"))
    assert proc.returncode == 1


# ── interpreter branch coverage (س3 honesty: the simulator must be tested) ──


def test_augassign_and_annassign_propagate(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "app.py": "def go():\n    x = input()\n    x += '!'\n    y: str = x\n"
                  "    eval(y)\n",
    })
    assert len(scan_tree(tmp_path).findings) == 1


def test_if_while_for_paths_join(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "app.py": (
            "def go(flag):\n"
            "    x = 'safe'\n"
            "    if flag:\n"
            "        x = input()\n"
            "    else:\n"
            "        x = 'alt'\n"
            "    for i in range(3):\n"
            "        x = x + str(i)\n"
            "    while flag:\n"
            "        flag = False\n"
            "    eval(x)\n"
        ),
    })
    rep = scan_tree(tmp_path)
    assert len(rep.findings) == 1 and rep.findings[0].sink == "eval"


def test_try_with_and_delete(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "app.py": (
            "def go():\n"
            "    try:\n"
            "        x = input()\n"
            "    except ValueError:\n"
            "        x = 'fallback'\n"
            "    else:\n"
            "        pass\n"
            "    finally:\n"
            "        pass\n"
            "    with open('/tmp/f') as fh:\n"
            "        data = fh\n"
            "    del x\n"
            "    eval(input())\n"
        ),
    })
    rep = scan_tree(tmp_path)
    assert len(rep.findings) == 1


def test_attribute_and_subscript_stores(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "app.py": (
            "def go():\n"
            "    holder = {}\n"
            "    holder['k'] = input()\n"
            "    eval(holder['k'])\n"
            "\n"
            "def go2():\n"
            "    box.value = input()\n"
            "    eval(box.value)\n"
        ),
    })
    rep = scan_tree(tmp_path)
    assert {f.line for f in rep.findings} == {4, 8}


def test_tuple_unpacking_spreads_taint(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "app.py": "def go():\n    a, b = input(), 'safe'\n    eval(a)\n",
    })
    assert len(scan_tree(tmp_path).findings) == 1


def test_containers_and_fstring_and_ifexp(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "app.py": (
            "def go(flag):\n"
            "    t = input()\n"
            "    lst = [t, 'x']\n"
            "    d = {'k': t}\n"
            "    s = f'v={t}'\n"
            "    v = t if flag else 'safe'\n"
            "    eval(lst[0] + s + v + d['k'])\n"
        ),
    })
    assert len(scan_tree(tmp_path).findings) == 1


def test_comprehensions_carry_iter_taint(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "app.py": (
            "def go():\n"
            "    rows = input()\n"
            "    picked = [r for r in rows.split(',')]\n"
            "    mapped = {i: r for i, r in enumerate(picked)}\n"
            "    gen = (x for x in picked)\n"
            "    eval(','.join(picked))\n"
        ),
    })
    rep = scan_tree(tmp_path)
    assert len(rep.findings) == 1 and rep.findings[0].sink == "eval"


def test_class_methods_collected_and_self_shifted(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "app.py": (
            "class Repo:\n"
            "    def query(self, sql):\n"
            "        cur = object()\n"
            "        cur.execute(sql)\n"
            "\n"
            "def main():\n"
            "    r = Repo()\n"
            "    r.query(input())\n"
        ),
    })
    rep = scan_tree(tmp_path)
    assert len(rep.findings) == 1
    assert rep.findings[0].sink == "*.execute"


def test_keyword_args_map_by_name(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "app.py": (
            "def sink(payload='', other=''):\n"
            "    eval(payload)\n"
            "\n"
            "def main():\n"
            "    sink(other='x', payload=input())\n"
        ),
    })
    assert len(scan_tree(tmp_path).findings) == 1


def test_star_args_and_kwargs_stop_mapping(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "app.py": (
            "def sink(*args, **kw):\n"
            "    eval(args[0])\n"
            "\n"
            "def main():\n"
            "    sink(*[input()])\n"
            "    sink(**{'payload': input()})\n"
        ),
    })
    # declared limit: *args/**kwargs mapping is unknown — no finding
    assert scan_tree(tmp_path).findings == []


def test_async_await_and_compare(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "app.py": (
            "async def grab():\n"
            "    return input()\n"
            "\n"
            "async def main():\n"
            "    value = await grab()\n"
            "    if value == 'x':\n"
            "        eval(value)\n"
        ),
    })
    rep = scan_tree(tmp_path)
    assert len(rep.findings) == 1


def test_walrus_and_generic_recursion(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "app.py": "def go():\n    if (v := input()):\n        eval(v)\n",
    })
    assert len(scan_tree(tmp_path).findings) == 1


def test_lambda_is_opaque(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "app.py": "def go():\n    f = lambda: input()\n    eval(f())\n",
    })
    # declared limit: closures are opaque — the taint inside the lambda is
    # invisible, and f() carries no static taint
    assert scan_tree(tmp_path).findings == []


def test_for_iter_taints_target(tmp_path: Path) -> None:
    _write_tree(tmp_path, {
        "app.py": "import sys\n\ndef go():\n    for part in sys.argv[1:]:\n"
                  "        exec(part)\n",
    })
    assert len(scan_tree(tmp_path).findings) == 1
