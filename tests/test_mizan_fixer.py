"""س1 regression tests — the MIZAN auto-fix engine (docs/MIZAN_ROADMAP.md).

Gap closed: Snyk-class engines open Fix PRs; MIZAN was read-only. These
tests pin the deterministic planner's contract: minimal safe bump, byte-exact
manifest preservation outside the changed specs, honest skips, honest
degradation, and the least-privilege workflow (ض10 lessons).
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from src.mizan.advisories import (
    Advisory,
    AdvisoryError,
    fetch_osv,
    load_offline,
)
from src.mizan.fixer import apply_plans, plan_fixes, render_diff
from src.mizan.manifest import (
    compare_versions,
    normalize_name,
    parse_requirements,
    replace_spec,
)

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "mizan" / "mizan_fix.py"
_WORKFLOWS = _ROOT / ".github" / "workflows"


def _adv(
    pkg: str = "requests",
    fixed: str = "2.31.0",
    vuln: str = "<2.31.0",
    ids: tuple[str, ...] = ("GHSA-1111-2222-3333",),
    severity: str = "HIGH",
) -> Advisory:
    return Advisory(package=pkg, vulnerable=vuln, fixed=fixed,
                    ids=ids, severity=severity)


def _plan(manifest: str, advisories: list[Advisory]):
    reqs = parse_requirements(manifest)
    return reqs, plan_fixes(reqs, advisories)


# ── normalize_name (PEP 503) ────────────────────────────────────────────────


@pytest.mark.parametrize("raw,expected", [
    ("Django", "django"),
    ("python-dateutil", "python-dateutil"),
    ("python_dateutil", "python-dateutil"),
    ("typing.extensions", "typing-extensions"),
    ("Typing__Extensions", "typing-extensions"),
])
def test_normalize_name_pep503(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


# ── compare_versions (documented subset) ───────────────────────────────────


@pytest.mark.parametrize("a,b,sign", [
    ("1.9", "1.10", -1),
    ("1.10", "1.9", 1),
    ("1.0", "1.0.0", 0),
    ("2.31.0", "2.31", 0),
    ("1.0rc1", "1.0", -1),
    ("1.0", "1.0.post1", -1),
    ("1.0.dev1", "1.0a1", -1),
    ("1.0b2", "1.0rc1", -1),
    ("v2.0", "2.0", 0),
    ("1.2.3", "1.2.4", -1),
])
def test_compare_versions_subset(a: str, b: str, sign: int) -> None:
    assert compare_versions(a, b) == sign


def test_compare_versions_garbage_sorts_lowest_not_crash() -> None:
    assert compare_versions("not-a-version", "1.0.0") == -1


# ── parse_requirements: byte-exact round-trip ──────────────────────────────


MANIFEST = """\
# runtime deps — keep pinned tight
requests>=2.28,<2.31  # vulnerable range (س1 fixture)
django==4.2.11
python-dateutil
colors[css]>=1.0 ; python_version < "3.12"
git+https://example.com/pkg.git#egg=x
-r other.txt
--index-url https://pypi.org/simple
not a requirement line!!!
flask == 1.1.1
"""

REQS = parse_requirements(MANIFEST)


def test_round_trip_is_byte_exact() -> None:
    assert "\n".join(ln.raw for ln in REQS) + "\n" == MANIFEST


def test_blank_and_whitespace_lines_survive_round_trip() -> None:
    text = "\n\n  \nrequests<2.31.0\n\n"
    reqs = parse_requirements(text)
    assert "\n".join(ln.raw for ln in reqs) + "\n" == text
    assert all(not ln.is_requirement for ln in reqs[:3])


def test_parse_classifies_lines() -> None:
    by_idx = {ln.index: ln for ln in REQS}
    assert by_idx[0].is_requirement is False            # comment
    assert by_idx[1].is_requirement and by_idx[1].name == "requests"
    assert by_idx[1].spec == ">=2.28,<2.31"
    assert by_idx[2].name == "django" and by_idx[2].spec == "==4.2.11"
    assert by_idx[3].name == "python-dateutil" and by_idx[3].spec == ""
    assert by_idx[4].name == "colors" and by_idx[4].spec == ">=1.0"
    assert by_idx[5].direct_url and by_idx[5].name == ""  # legacy VCS line
    assert by_idx[6].is_requirement is False            # -r option
    assert by_idx[7].is_requirement is False            # --index-url
    assert by_idx[8].parse_error                        # "not a requirement line!!!"
    # internal spacing is preserved inside the spec (byte-exact reconstruction)
    assert by_idx[9].spec == "== 1.1.1" and by_idx[9].head == "flask "


def test_pep508_direct_reference_name_is_extracted() -> None:
    reqs = parse_requirements("pkg @ https://example.com/pkg-1.0.whl\n")
    assert reqs[0].direct_url and reqs[0].name == "pkg"


def test_line_without_name_is_unparseable_not_crash() -> None:
    reqs = parse_requirements("+=???\n")
    assert reqs[0].parse_error == "unparseable requirement"


def test_replace_spec_rewrites_only_version() -> None:
    ln = REQS[1]
    assert replace_spec(ln, "==2.31.0") == \
        "requests==2.31.0  # vulnerable range (س1 fixture)"


def test_replace_spec_never_touches_non_requirements() -> None:
    for i in (0, 5, 6, 7, 8):
        assert replace_spec(REQS[i], "==9.9.9") == REQS[i].raw


def test_replace_spec_preserves_environment_marker() -> None:
    # Regression: a rewrite once dropped the `; python_version < "3.12"` tail.
    out = replace_spec(REQS[4], "==1.9")
    assert out == 'colors[css]==1.9 ; python_version < "3.12"'


def test_head_spec_tail_invariant_holds_for_every_line() -> None:
    for ln in REQS:
        if ln.is_requirement and not ln.direct_url:
            assert ln.head + ln.spec + ln.tail == ln.raw


def test_bare_requirement_gains_pin_with_space() -> None:
    ln = REQS[3]
    assert replace_spec(ln, "==2.8.2") == "python-dateutil==2.8.2"


# ── plan_fixes: the deterministic contract ─────────────────────────────────


def test_plan_minimal_bump_for_range() -> None:
    _, result = _plan(MANIFEST, [_adv()])
    assert len(result.plans) == 1
    p = result.plans[0]
    assert p.package == "requests"
    assert p.target_spec == "==2.31.0"
    assert p.line_index == 1
    assert "GHSA-1111-2222-3333" in p.advisory_ids


def test_plan_skips_when_no_fixed_version_declared() -> None:
    _, result = _plan(MANIFEST, [_adv(fixed="", vuln="<99")])
    assert not result.changed
    assert result.skipped[0].reason.startswith("no fixed version declared")


def test_plan_skips_exact_pin_already_at_fix() -> None:
    _, result = _plan(MANIFEST, [_adv(pkg="django", fixed="4.2.11")])
    assert not result.changed
    assert "already pinned" in result.skipped[0].reason


def test_plan_fixes_exact_pin_below_fix() -> None:
    _, result = _plan(MANIFEST, [_adv(pkg="flask", fixed="1.1.2")])
    assert result.plans[0].target_spec == "==1.1.2"
    assert result.plans[0].line_index == 9


def test_plan_conservative_on_unpinned_and_ranged() -> None:
    # bare `python-dateutil` + ranged requests both treated vulnerable.
    _, result = _plan(MANIFEST, [
        _adv(pkg="python-dateutil", fixed="2.8.2"),
        _adv(pkg="requests", fixed="2.31.0"),
    ])
    targets = {p.package: p.target_spec for p in result.plans}
    assert targets == {"requests": "==2.31.0", "python-dateutil": "==2.8.2"}


def test_plan_merges_advisories_and_takes_highest_fix() -> None:
    _, result = _plan(MANIFEST, [
        _adv(fixed="2.31.0", ids=("CVE-1",), severity="MEDIUM"),
        _adv(fixed="2.32.3", ids=("CVE-2",), severity="CRITICAL"),
    ])
    p = result.plans[0]
    assert p.target_spec == "==2.32.3"
    assert p.severity == "CRITICAL"
    assert p.advisory_ids == ("CVE-2", "CVE-1")  # by descending severity


def test_plan_ignores_packages_without_advisories_and_direct_urls() -> None:
    _, result = _plan(MANIFEST, [_adv(pkg="totally-absent"), _adv(pkg="flask")])
    assert {p.package for p in result.plans} == {"flask"}


def test_plan_display_name_preserved() -> None:
    manifest = "Requests>=2.28,<2.31\n"
    _, result = _plan(manifest, [_adv()])
    assert result.plans[0].display_name == "Requests"
    assert result.plans[0].package == "requests"


# ── apply_plans: byte-exact outside the fix ────────────────────────────────


def test_apply_rewrites_only_target_lines() -> None:
    reqs, result = _plan(MANIFEST, [_adv()])
    updated = apply_plans(MANIFEST, reqs, result.plans)
    expected = MANIFEST.replace("requests>=2.28,<2.31", "requests==2.31.0")
    assert updated == expected


def test_apply_preserves_missing_trailing_newline() -> None:
    manifest = "requests<2.31.0"
    reqs, result = _plan(manifest, [_adv()])
    updated = apply_plans(manifest, reqs, result.plans)
    assert updated == "requests==2.31.0"
    assert not updated.endswith("\n")


def test_apply_refuses_no_op_write() -> None:
    reqs = parse_requirements(MANIFEST)
    with pytest.raises(ValueError, match="no plans"):
        apply_plans(MANIFEST, reqs, [])


def test_render_diff_unified_and_empty_when_identical() -> None:
    reqs, result = _plan(MANIFEST, [_adv()])
    updated = apply_plans(MANIFEST, reqs, result.plans)
    diff = render_diff(MANIFEST, updated)
    assert diff.startswith("--- a/requirements.txt")
    assert "+requests==2.31.0" in diff
    assert "-requests>=2.28,<2.31" in diff
    assert render_diff(MANIFEST, MANIFEST) == ""


# ── load_offline: deterministic fixture source ─────────────────────────────


def test_load_offline_accepts_bare_list_and_dict_wrapper(tmp_path: Path) -> None:
    # one row with a string id, one with an id list, one with both ranges
    rows = (
        '[{"package": "requests", "vulnerable": "<2.31.0", '
        '"fixed": "2.31.0", "ids": "CVE-X", "severity": "high"}, '
        '{"package": "flask", "vulnerable": "<1", "fixed": "1.1.2", '
        '"ids": ["GHSA-A", "CVE-Y"], "severity": "MEDIUM"}, '
        '{"package": "django", "vulnerable": ">=4,<4.2", '
        '"fixed": "4.2.11", "ids": []}]'
    )
    p1 = tmp_path / "bare.json"
    p1.write_text(rows, encoding="utf-8")
    p2 = tmp_path / "wrapped.json"
    p2.write_text('{"advisories": ' + rows + "}", encoding="utf-8")
    for p in (p1, p2):
        advs = load_offline(p)
        assert advs[0].name == "requests"
        assert advs[0].ids == ("CVE-X",)
        assert advs[0].severity == "HIGH"  # normalized upper
        assert advs[1].ids == ("GHSA-A", "CVE-Y")  # list ids pass through
        assert advs[2].ids == ()


@pytest.mark.parametrize("content,match", [
    ("not json", "cannot read"),
    ('{"nope": 1}', "must be a list"),
    ('[{"vulnerable": "<1"}]', "missing 'package'"),
    ('[{"package": "x"}]', "needs 'fixed' or 'vulnerable'"),
])
def test_load_offline_rejects_malformed(tmp_path: Path, content: str,
                                        match: str) -> None:
    p = tmp_path / "bad.json"
    p.write_text(content, encoding="utf-8")
    with pytest.raises(AdvisoryError, match=match):
        load_offline(p)


def test_load_offline_missing_file_is_error(tmp_path: Path) -> None:
    with pytest.raises(AdvisoryError, match="cannot read"):
        load_offline(tmp_path / "absent.json")


# ── fetch_osv: injectable HTTP, honest failure ─────────────────────────────


def _osv_batch(*pkg_ids: list[dict]) -> dict:
    return {"results": [{"vulns": [{"id": v["id"]} for v in ids]}
                        for ids in pkg_ids]}


def test_fetch_osv_success_path(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.mizan.advisories as mod

    calls: list[str] = []

    def fake_http(url: str, payload: dict | None, timeout: float) -> dict:
        calls.append(url)
        if "querybatch" in url:
            assert payload is not None and payload["queries"][0]["package"] == {
                "name": "requests", "ecosystem": "PyPI"}
            return _osv_batch([{"id": "GHSA-A"}, {"id": "GHSA-B"}])
        detail = {
            "affected": [{
                "package": {"name": "requests", "ecosystem": "PyPI"},
                "ranges": [{"events": [
                    {"introduced": "2.28"}, {"fixed": "2.31.0"}]}],
            }],
            "aliases": ["CVE-2025-999"],
            "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/H:H"}],
        } if "GHSA-A" in url else {"affected": []}
        return detail

    monkeypatch.setattr(mod, "_http_json", fake_http)
    advs = fetch_osv(["requests"])
    assert len(calls) == 3  # batch + 2 details
    assert len(advs) == 1  # GHSA-B has no PyPI affected entry → dropped
    a = advs[0]
    assert (a.vulnerable, a.fixed) == (">=2.28,<2.31.0", "2.31.0")
    assert a.ids == ("GHSA-A", "CVE-2025-999")
    assert a.severity == "CVSS:3.1/AV:N/H:H"


def test_fetch_osv_network_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.mizan.advisories as mod

    def boom(url: str, payload: dict | None, timeout: float) -> dict:
        raise OSError("network down")

    monkeypatch.setattr(mod, "_http_json", boom)
    with pytest.raises(AdvisoryError, match="OSV.dev unreachable"):
        fetch_osv(["requests"])


def test_fetch_osv_detail_failure_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.mizan.advisories as mod

    def fake_http(url: str, payload: dict | None, timeout: float) -> dict:
        if "querybatch" in url:
            return _osv_batch([{"id": "GHSA-A"}, {"id": "GHSA-B"}])
        if "GHSA-A" in url:
            return {"affected": [{
                "package": {"name": "requests", "ecosystem": "PyPI"},
                "ranges": [{"events": [{"fixed": "2.31.0"}]}],
            }]}
        raise OSError("transient")

    monkeypatch.setattr(mod, "_http_json", fake_http)
    advs = fetch_osv(["requests"])
    assert [a.ids[0] for a in advs] == ["GHSA-A"]


def test_fetch_osv_details_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.mizan.advisories as mod

    monkeypatch.setattr(mod, "_MAX_DETAIL_FETCH", 1)
    seen: list[str] = []

    def fake_http(url: str, payload: dict | None, timeout: float) -> dict:
        if "querybatch" in url:
            return _osv_batch([{"id": "GHSA-A"}, {"id": "GHSA-B"}])
        seen.append(url.rsplit("/", 1)[-1])
        return {"affected": [{
            "package": {"name": "requests", "ecosystem": "PyPI"},
            "ranges": [{"events": [{"fixed": "2.31.0"}]}],
        }]}

    monkeypatch.setattr(mod, "_http_json", fake_http)
    fetch_osv(["requests"])
    assert seen == ["GHSA-A"]  # capped to one detail fetch


def test_fetch_osv_without_fixed_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.mizan.advisories as mod

    def fake_http(url: str, payload: dict | None, timeout: float) -> dict:
        if "querybatch" in url:
            return _osv_batch([{"id": "GHSA-A"}])
        return {"affected": [{
            "package": {"name": "requests", "ecosystem": "PyPI"},
            "ranges": [{"events": [{"introduced": "0"}]}],  # no fixed event
        }]}

    monkeypatch.setattr(mod, "_http_json", fake_http)
    assert fetch_osv(["requests"]) == []


def test_fetch_osv_end_to_end_over_local_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the real urllib path against a localhost OSV stand-in.

    No external network: a stdlib HTTPServer thread plays the OSV API and
    covers the actual ``_http_json`` exchange, duplicate-id dedupe and the
    no-severity default in one deterministic pass.
    """
    import json as _json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import src.mizan.advisories as mod

    batch = _osv_batch([{"id": "GHSA-A"}, {"id": "GHSA-A"}, {"id": "GHSA-B"}])
    details = {
        "GHSA-A": {"affected": [{
            "package": {"name": "requests", "ecosystem": "PyPI"},
            "ranges": [{"events": [
                {"introduced": "2.28"}, {"fixed": "2.31.0"}]}],
        }]},  # no severity block → UNKNOWN
        "GHSA-B": {"affected": [
            {"package": {"name": "not-on-pypi", "ecosystem": "npm"}},  # skipped
            {"package": {"name": "requests", "ecosystem": "PyPI"},
             "ranges": [{"events": [{"fixed": "2.32.0"}]}],
             "versions": ["2.31.0"]},
        ], "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N"}],
        },
    }
    seen_paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def _send(self, payload: dict) -> None:
            body = _json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802 — http.server naming
            seen_paths.append(self.path)
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            self._send(batch)

        def do_GET(self) -> None:  # noqa: N802 — http.server naming
            seen_paths.append(self.path)
            vid = self.path.rsplit("/", 1)[-1]
            self._send(details[vid])

        def log_message(self, *args: object) -> None:  # silence the thread
            return None

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(mod, "osv_url", f"http://127.0.0.1:{server.server_port}")
    try:
        advs = fetch_osv(["requests"])
    finally:
        server.shutdown()
        server.server_close()

    assert seen_paths[0] == "/v1/querybatch"
    assert len(seen_paths) == 3  # dedupe: A fetched once, B once
    a, b = advs
    assert (a.fixed, a.severity) == ("2.31.0", "UNKNOWN")
    assert a.vulnerable == ">=2.28,<2.31.0"
    assert (b.fixed, b.severity) == ("2.32.0", "CVSS:3.1/AV:N")
    assert b.vulnerable == "<2.32.0"  # no introduced event → plain "<fix"


# ── CLI: subprocess contract (scripts are outside the coverage gate) ───────


def _script_env() -> dict[str, str]:
    import os
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    return env


def _write_manifest(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "requirements.txt"
    p.write_text(text, encoding="utf-8")
    return p


def _write_advisories(tmp_path: Path, rows: str) -> Path:
    p = tmp_path / "adv.json"
    p.write_text(rows, encoding="utf-8")
    return p


ADV = ('[{"package": "requests", "vulnerable": "<2.31.0", '
       '"fixed": "2.31.0", "ids": ["GHSA-x"], "severity": "HIGH"}]')


def test_cli_plan_exits_two_and_prints_diff(tmp_path: Path) -> None:
    m = _write_manifest(tmp_path, "requests<2.31.0\n")
    a = _write_advisories(tmp_path, ADV)
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), str(m), "--advisories", str(a)],
        capture_output=True, text=True, cwd=str(tmp_path), env=_script_env(),
        timeout=60,
    )
    assert proc.returncode == 2
    assert "requests: <2.31.0 → ==2.31.0" in proc.stdout
    assert "+requests==2.31.0" in proc.stdout
    assert m.read_text(encoding="utf-8") == "requests<2.31.0\n"  # dry-run


def test_cli_apply_rewrites_and_exits_zero(tmp_path: Path) -> None:
    m = _write_manifest(tmp_path, "requests<2.31.0\n")
    a = _write_advisories(tmp_path, ADV)
    diff_path = tmp_path / "fix.diff"
    report = tmp_path / "report.md"
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), str(m), "--advisories", str(a),
         "--apply", "--diff-file", str(diff_path), "--report-md", str(report)],
        capture_output=True, text=True, cwd=str(tmp_path), env=_script_env(),
        timeout=60,
    )
    assert proc.returncode == 0
    assert m.read_text(encoding="utf-8") == "requests==2.31.0\n"
    assert "+requests==2.31.0" in diff_path.read_text(encoding="utf-8")
    body = report.read_text(encoding="utf-8")
    assert "MIZAN auto-fix" in body and "==2.31.0" in body


def test_cli_clean_manifest_exits_zero(tmp_path: Path) -> None:
    m = _write_manifest(tmp_path, "requests==2.31.0\n")
    a = _write_advisories(tmp_path, ADV)
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), str(m), "--advisories", str(a)],
        capture_output=True, text=True, cwd=str(tmp_path), env=_script_env(),
        timeout=60,
    )
    assert proc.returncode == 0
    assert "no actionable fixes" in proc.stdout


def test_cli_missing_manifest_exits_one(tmp_path: Path) -> None:
    a = _write_advisories(tmp_path, ADV)
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "nope.txt", "--advisories", str(a)],
        capture_output=True, text=True, cwd=str(tmp_path), env=_script_env(),
        timeout=60,
    )
    assert proc.returncode == 1
    assert "cannot read" in proc.stderr


def test_cli_degraded_osv_is_honest_noop(tmp_path: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """Unreachable intel ⇒ loud stderr note + exit 0, never fake output."""
    spec = importlib.util.spec_from_file_location("mizan_fix_under_test", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def unreachable(packages: list[str], timeout: float = 10.0) -> list[Advisory]:
        raise AdvisoryError("OSV.dev unreachable: simulated outage")

    monkeypatch.setattr(mod, "fetch_osv", unreachable)
    m = _write_manifest(tmp_path, "requests<2.31.0\n")
    rc = mod.main([str(m), "--osv"])
    assert rc == 0
    assert m.read_text(encoding="utf-8") == "requests<2.31.0\n"  # untouched


def test_cli_advisory_source_is_required(tmp_path: Path) -> None:
    m = _write_manifest(tmp_path, "requests<2.31.0\n")
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), str(m)],
        capture_output=True, text=True, cwd=str(tmp_path), env=_script_env(),
        timeout=60,
    )
    assert proc.returncode == 2  # argparse usage error


def test_cli_report_lists_skips(tmp_path: Path) -> None:
    rows = ('[{"package": "requests", "vulnerable": "<9", "fixed": "", '
            '"ids": ["GHSA-no-fix"]}]')
    m = _write_manifest(tmp_path, "requests==2.31.0\n")
    a = _write_advisories(tmp_path, rows)
    report = tmp_path / "r.md"
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), str(m), "--advisories", str(a),
         "--report-md", str(report)],
        capture_output=True, text=True, cwd=str(tmp_path), env=_script_env(),
        timeout=60,
    )
    assert proc.returncode == 0
    assert "no fixed version declared" in report.read_text(encoding="utf-8")


# ── workflow posture (ض10 lessons stay enforced) ────────────────────────────


def test_mizan_fix_workflow_never_uses_pr_target() -> None:
    text = (_WORKFLOWS / "mizan-fix.yml").read_text(encoding="utf-8")
    assert "pull_request_target" not in text
    assert "git add ." not in text
    assert "git add requirements.txt" in text


def test_mizan_fix_workflow_is_least_privilege() -> None:
    text = (_WORKFLOWS / "mizan-fix.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read\n" in text  # workflow level: read
    job = text.split("autofix:", 1)[1]
    assert "contents: write" in job  # only the single autofix job may write
    assert "pull-requests: write" in job
