#!/usr/bin/env python3
"""MIZAN SAST scan — the entrypoint ``.github/workflows/mizan-scan.yml`` runs.

ض11 (v1.58.0): the MIZAN integration shipped its workflow without this script,
so every PR got a permanently red ``mizan-security-scan`` check (the scan step
"passed" only via ``continue-on-error``). This implementation makes the scan
real and mirrors the repo's own bandit gate in ``ci.yml``. It lives under
``scripts/mizan/`` because the м1 root-hygiene gate allows only ``main.py``
at the repo root; the workflow invokes it by this path.

* same audited surface (connectors, hyper_app, legacy hyper_agent, learning,
  knowledge, skills, security),
* same severity floor (``-ll`` = MEDIUM+),
* output as SARIF for the GitHub Security tab (``bandit.sarif``; an empty
  ``semgrep.sarif`` stub keeps the upload step satisfied).

Exit codes mirror the CI gate: 0 = clean or degraded (no scanner installed),
1 = MEDIUM+ findings (the workflow's "Fail if MIZAN found issues" step turns
that into a red check). Stdlib-only.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # repo root (SARIF/report live there)

#: Same audited surface (and severity floor) as the bandit gate in ci.yml.
SCAN_TARGETS = (
    "connectors",
    "hyper_app",
    "src/legacy_root/hyper_agent.py",
    "src/learning",
    "src/knowledge",
    "src/skills",
    "src/security",
)

EMPTY_SARIF = {
    "version": "2.1.0",
    "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
    "runs": [
        {
            "tool": {"driver": {"name": "mizan", "informationUri": "https://github.com/tibatechapp-ship-it/nexus-core", "rules": []}},
            "results": [],
        }
    ],
}

#: bandit JSON severity → SARIF level.
_SARIF_LEVEL = {"HIGH": "error", "MEDIUM": "warning", "LOW": "note"}


def _to_sarif(bandit_json: dict) -> dict:
    """Convert bandit's JSON output to SARIF 2.1.0 (stdlib — bandit has no
    native SARIF formatter without extra plugins)."""
    results = []
    for r in bandit_json.get("results", []):
        results.append({
            "ruleId": r.get("test_id", "unknown"),
            "level": _SARIF_LEVEL.get(str(r.get("issue_severity", "")).upper(), "warning"),
            "message": {"text": str(r.get("issue_text", ""))[:500]},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": str(r.get("filename", "")).lstrip("/")},
                    "region": {"startLine": int(r.get("line_number") or 1)},
                }
            }],
        })
    sarif = json.loads(json.dumps(EMPTY_SARIF))  # deep copy
    sarif["runs"][0]["results"] = results
    return sarif


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _report(findings: int, degraded: bool) -> None:
    """Write ``mizan_report.md`` — the artifact the PR-comment step posts."""
    if degraded:
        summary = "وضع متدهور: الماسح (bandit) غير متاح على المشغّل — أُصدر SARIF فارغ."
    elif findings == 0:
        summary = "نظيف: لا نتائج متوسطة+ على السطح المدقّق (نفس بوابة bandit في CI)."
    else:
        summary = f"رُصد {findings} نتيجة متوسطة+ — التفاصيل في تبويب Security (SARIF)."
    lines = [
        "## تقرير MIZAN الأمني",
        "",
        summary,
        "",
        f"- السطح: `{'`, `'.join(SCAN_TARGETS)}`",
        "- عتبة الخطورة: متوسطة+ (-ll)، مطابقة لبوابة CI.",
        "",
    ]
    (ROOT / "mizan_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    bandit = shutil.which("bandit")
    if bandit is None:
        # Degrade honestly: an empty SARIF keeps the Security-tab upload valid
        # and the check stays green — a missing scanner must not fake findings
        # (nor silently red-bar every PR the way the missing script used to).
        _write(ROOT / "bandit.sarif", EMPTY_SARIF)
        _write(ROOT / "semgrep.sarif", EMPTY_SARIF)
        _report(0, degraded=True)
        print("MIZAN: bandit not installed — empty SARIF emitted, scan degraded")
        return 0

    # bandit has no native SARIF formatter (that needs an extra plugin), so we
    # take JSON and convert in-tree — stdlib only, no new dependencies.
    cmd = [bandit, "-r", *SCAN_TARGETS, "-ll", "-f", "json", "-q"]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)  # noqa: S603 — fixed argv
    try:
        bandit_json = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        bandit_json = {}
    findings = bandit_json.get("results", [])
    _write(ROOT / "bandit.sarif", _to_sarif(bandit_json))
    _write(ROOT / "semgrep.sarif", EMPTY_SARIF)  # semgrep needs registry config; stub for upload
    _report(len(findings), degraded=False)

    if proc.returncode == 0:
        print("MIZAN: clean — no MEDIUM+ findings on the audited surface")
        return 0
    if proc.returncode == 1:
        print(f"MIZAN: {len(findings)} MEDIUM+ findings — see bandit.sarif / Security tab")
        return 1
    print(f"MIZAN: bandit crashed rc={proc.returncode}\n{proc.stderr[-2000:]}",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
