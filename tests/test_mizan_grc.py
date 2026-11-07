"""س5 regression tests — the static GRC dashboard (docs/MIZAN_ROADMAP.md).

Gap closed: no central governance view. These tests pin the س5 exit gate:
a dashboard generated from two known fake reports matches the numbers by
test, the HTML is a self-contained RTL Arabic file with zero JS, findings
strings are HTML-escaped, control maps ship as a reviewed data file labeled
"proposed coverage", and the CLI wires it together.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.mizan.grc import (
    SCHEMA,
    GrcError,
    aggregate,
    control_coverage,
    controls_path,
    load_controls,
    load_report,
    render_html,
)

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "mizan" / "mizan_grc.py"


def _report(
    path: Path, repo: str, generated_at: str, findings: list[dict],
    fixes: dict | None = None,
) -> Path:
    payload = {
        "schema": SCHEMA,
        "repo": repo,
        "generated_at": generated_at,
        "findings": findings,
    }
    if fixes is not None:
        payload["fixes"] = fixes
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ── the س5 exit gate: two known fake reports → numbers match ─────────────────


@pytest.fixture()
def two_reports(tmp_path: Path) -> list[Path]:
    a = _report(tmp_path / "a.json", "alpha", "2026-11-07T10:00:00+00:00", [
        {"rule_id": "B307", "severity": "HIGH", "message": "eval use",
         "path": "x.py", "line": 3, "state": "open"},
        {"rule_id": "B101", "severity": "LOW", "message": "assert",
         "path": "y.py", "line": 9, "state": "fixed"},
    ], fixes={"planned": 2, "applied": 1})
    b = _report(tmp_path / "b.json", "beta", "2026-11-07T09:00:00+00:00", [
        {"rule_id": "B602", "severity": "CRITICAL", "message": "shell=True",
         "path": "z.py", "line": 1, "state": "open"},
        {"rule_id": "B102", "severity": "MEDIUM", "message": "exec",
         "path": "z.py", "line": 2, "state": "suppressed"},
    ])
    return [a, b]


def test_numbers_match_two_known_reports(two_reports: list[Path]) -> None:
    portfolio = aggregate([load_report(p) for p in two_reports])
    totals = portfolio.by_severity()
    # beta's MEDIUM is suppressed; alpha's LOW is fixed → 1 HIGH + 1 CRITICAL
    assert totals == {
        "CRITICAL": 1, "HIGH": 1, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0,
    }
    assert portfolio.by_repo() == {"alpha": 1, "beta": 1}
    assert portfolio.fixes() == (2, 1)
    top = portfolio.top_risks(1)
    assert top[0].rule_id == "B602" and top[0].repo == "beta"
    trend = portfolio.trend()
    assert trend == [("2026-11-07", 2)]


def test_latest_report_per_repo_wins(tmp_path: Path) -> None:
    old = _report(tmp_path / "old.json", "alpha", "2026-11-01T00:00:00+00:00", [
        {"rule_id": "B307", "severity": "HIGH", "message": "m",
         "path": "x.py", "line": 1, "state": "open"},
        {"rule_id": "B101", "severity": "LOW", "message": "m",
         "path": "x.py", "line": 2, "state": "open"},
    ])
    new = _report(tmp_path / "new.json", "alpha", "2026-11-07T00:00:00+00:00", [
        {"rule_id": "B307", "severity": "HIGH", "message": "m",
         "path": "x.py", "line": 1, "state": "open"},
    ])
    portfolio = aggregate([load_report(old), load_report(new)])
    assert portfolio.by_repo() == {"alpha": 1}


# ── report validation ────────────────────────────────────────────────────────


def test_load_report_rejects_bad_input(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    with pytest.raises(GrcError, match="cannot read"):
        load_report(bad)
    noschema = tmp_path / "s.json"
    noschema.write_text('{"schema": "other/1", "repo": "r", "findings": []}',
                        encoding="utf-8")
    with pytest.raises(GrcError, match="unsupported schema"):
        load_report(noschema)
    norepo = tmp_path / "r.json"
    norepo.write_text('{"schema": "mizan.grc/1", "findings": []}', encoding="utf-8")
    with pytest.raises(GrcError, match="missing 'repo'"):
        load_report(norepo)
    nofind = tmp_path / "f.json"
    nofind.write_text('{"schema": "mizan.grc/1", "repo": "r"}', encoding="utf-8")
    with pytest.raises(GrcError, match="findings"):
        load_report(nofind)
    badrow = tmp_path / "row.json"
    badrow.write_text('{"schema": "mizan.grc/1", "repo": "r", "findings": [3]}',
                      encoding="utf-8")
    with pytest.raises(GrcError, match="#0"):
        load_report(badrow)
    badfix = tmp_path / "fix.json"
    badfix.write_text(
        '{"schema": "mizan.grc/1", "repo": "r", "findings": [], "fixes": 3}',
        encoding="utf-8",
    )
    with pytest.raises(GrcError, match="fixes"):
        load_report(badfix)


def test_unknown_severity_lands_in_unknown(tmp_path: Path) -> None:
    p = _report(tmp_path / "u.json", "u", "2026-11-07T00:00:00+00:00", [
        {"rule_id": "X1", "severity": "weird", "message": "m",
         "path": "a.py", "line": 1, "state": "open"},
    ])
    portfolio = aggregate([load_report(p)])
    assert portfolio.by_severity()["UNKNOWN"] == 1


# ── HTML rendering ───────────────────────────────────────────────────────────


def test_render_html_is_rtl_arabic_zero_js(two_reports: list[Path]) -> None:
    portfolio = aggregate([load_report(p) for p in two_reports])
    html = render_html(portfolio, load_controls())
    assert 'lang="ar" dir="rtl"' in html
    assert "<script" not in html
    assert "ميزان GRC" in html
    assert "تغطية مقترحة" in html          # honesty label present
    assert "A.8.8" in html                  # ISO 27001 control id rendered
    assert "CC7.1" in html and "6.2.1" in html


def test_render_html_escapes_finding_strings(two_reports: list[Path]) -> None:
    p = _report(two_reports[0].parent / "x.json", "x",
                "2026-11-07T00:00:00+00:00", [
        {"rule_id": "B1", "severity": "LOW",
         "message": "<script>alert(1)</script>",
         "path": "<img src=x>", "line": 1, "state": "open"},
    ])
    html = render_html(aggregate([load_report(p)]), None)
    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;" in html


def test_render_html_empty_portfolio() -> None:
    from src.mizan.grc import Portfolio

    html = render_html(Portfolio(), None)
    assert "لا تقارير" in html
    assert "لا مكتشفات مفتوحة" in html


# ── control coverage (reviewed data file) ────────────────────────────────────


def test_builtin_controls_file_loads() -> None:
    frameworks = load_controls()
    assert set(frameworks) == {"iso27001", "soc2", "pci_dss"}
    for rows in frameworks.values():
        assert rows and all("id" in r and "title" in r for r in rows)


def test_controls_path_is_packaged_data() -> None:
    assert controls_path().name == "controls.json"
    assert controls_path().exists()


def test_control_coverage_counts_open_findings(two_reports: list[Path]) -> None:
    portfolio = aggregate([load_report(p) for p in two_reports])
    frameworks = load_controls()
    rows = control_coverage(portfolio, frameworks)
    a88 = next(r for r in rows if r.control_id == "A.8.8")
    # open: B307 (HIGH) + B602 (CRITICAL) — both mapped to A.8.8
    assert a88.open_findings == 2


def test_load_controls_rejects_bad_file(tmp_path: Path) -> None:
    bad = tmp_path / "c.json"
    bad.write_text('{"frameworks": {}}', encoding="utf-8")
    with pytest.raises(GrcError, match="frameworks"):
        load_controls(bad)
    bad.write_text('{"frameworks": {"iso27001": [{"id": "1"}]}}', encoding="utf-8")
    with pytest.raises(GrcError, match="bad control row"):
        load_controls(bad)
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(GrcError, match="JSON object"):
        load_controls(bad)


# ── CLI ──────────────────────────────────────────────────────────────────────


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, timeout=120,
    )


def test_cli_end_to_end(two_reports: list[Path], tmp_path: Path) -> None:
    out = tmp_path / "dash.html"
    agg = tmp_path / "agg.json"
    proc = _run_cli(
        "--report", str(two_reports[0]), "--report", str(two_reports[1]),
        "--out", str(out), "--json", str(agg),
    )
    assert proc.returncode == 0, proc.stderr
    assert "repos=2" in proc.stdout and "open=2" in proc.stdout
    text = out.read_text(encoding="utf-8")
    assert 'dir="rtl"' in text
    payload = json.loads(agg.read_text(encoding="utf-8"))
    assert payload["totals"]["CRITICAL"] == 1
    assert payload["fixes"] == {"planned": 2, "applied": 1}


def test_cli_no_controls_and_errors(two_reports: list[Path],
                                    tmp_path: Path) -> None:
    out = tmp_path / "d.html"
    proc = _run_cli("--report", str(two_reports[0]),
                    "--no-controls", "--out", str(out))
    assert proc.returncode == 0
    text = out.read_text(encoding="utf-8")
    assert "A.8.8" not in text           # controls section absent
    assert "غير مفعّلة" in text          # explicit off-note instead
    proc = _run_cli("--report", str(tmp_path / "missing.json"), "--out", str(out))
    assert proc.returncode == 1
