"""Build a SHA-bound, sanitized evidence envelope for a GitHub PR.

This adapter runs MIZAN's read-only full-scan command. It never invokes any
repair, approval, transfer, or merge command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "nexus.security-evidence.v1"
REQUIRED_SCANNERS = (
    "analysis",
    "detection",
    "scanner",
    "git",
    "ci",
    "dependencies",
    "change_risk",
    "documentation",
)
MAX_REPORT_BYTES = 20 * 1024 * 1024

_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)(://[^:/\s]+:)[^@/\s]+(@)"),
    re.compile(
        r"""(?i)\b(api[_-]?key|access[_-]?token|client[_-]?secret|password|secret)"""
        r"""(\s*[:=]\s*)(["']?)[A-Za-z0-9_./+=:-]{8,}(["']?)"""
    ),
)
_SECRET_KEYS = ("password", "secret", "private_key", "access_token", "api_key", "client_secret", "credential")


def sanitize(value: Any, key: str = "") -> Any:
    """Redact obvious credentials before a report is uploaded as an artifact."""
    normalized_key = key.lower().replace("-", "_")
    if normalized_key in _SECRET_KEYS or normalized_key.endswith(("_secret", "_token", "_password", "_credential")):
        if isinstance(value, (str, int, float)) and value not in (None, ""):
            return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): sanitize(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(item, key) for item in value]
    if isinstance(value, str):
        result = value
        for pattern in _SECRET_PATTERNS:
            if pattern.groups:
                if pattern.pattern.startswith("(?i)\\b(api"):
                    result = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", result)
                elif pattern.pattern.startswith("(?i)(://"):
                    result = pattern.sub(r"\1[REDACTED]\2", result)
                else:
                    result = pattern.sub("[REDACTED]", result)
            else:
                result = pattern.sub("[REDACTED]", result)
        return result
    return value


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def incomplete_sources(scan: dict[str, Any]) -> list[str]:
    failed = scan.get("scanners_failed")
    if not isinstance(failed, list):
        raise ValueError("MIZAN report is missing scanners_failed[]")
    incomplete = [str(item) for item in failed]
    dependencies = scan.get("dependencies")
    if not isinstance(dependencies, dict):
        raise ValueError("MIZAN dependencies section is missing or invalid")
    if dependencies.get("osv_errors"):
        incomplete.append("osv")
    if dependencies.get("osv_unchecked"):
        incomplete.append("osv-offline")
    analysis = scan.get("analysis")
    if not isinstance(analysis, dict):
        raise ValueError("MIZAN analysis section is missing or invalid")
    if analysis.get("custom_rules_errors"):
        incomplete.append("custom-rules")
    for name in REQUIRED_SCANNERS:
        section = scan.get(name)
        if not isinstance(section, dict):
            incomplete.append(f"{name}-missing")
        elif section.get("error") and name not in incomplete:
            incomplete.append(name)
    return sorted(set(incomplete))



def scanner_statuses(scan: dict[str, Any], incomplete: list[str]) -> list[dict[str, Any]]:
    statuses = []
    for name in REQUIRED_SCANNERS:
        section = scan.get(name)
        related_incomplete = (
            name in incomplete
            or (name == "dependencies" and any(x.startswith("osv") for x in incomplete))
            or (name == "analysis" and "custom-rules" in incomplete)
        )
        error = section.get("error") if isinstance(section, dict) else "missing-or-invalid"
        statuses.append({
            "name": name,
            "status": "failed" if related_incomplete else "completed",
            "error": error,
        })
    return statuses

def build_envelope(
    scan: dict[str, Any],
    repository: str,
    pr_number: int,
    head_sha: str,
    base_sha: str,
    exit_code: int,
    timestamp: str | None = None,
) -> dict[str, Any]:
    if scan.get("engine") != "MIZAN Security Master Engine":
        raise ValueError("Unexpected MIZAN engine identity")
    if scan.get("mode") != "read-only" or scan.get("execution_performed") is not False:
        raise ValueError("MIZAN report does not prove read-only, non-executing mode")
    version = scan.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("MIZAN version is missing")
    incomplete = incomplete_sources(scan)
    expected_exit = 2 if incomplete else 0
    if exit_code != expected_exit:
        raise ValueError(
            f"MIZAN exit code {exit_code} contradicts report completeness "
            f"(expected {expected_exit})"
        )

    envelope: dict[str, Any] = {
        "schema_version": SCHEMA,
        "scan_id": hashlib.sha256(
            f"{repository}:{pr_number}:{head_sha}:{timestamp or ''}".encode()
        ).hexdigest(),
        "repository": repository,
        "pull_request": pr_number,
        "head_sha": head_sha,
        "base_sha": base_sha,
        "mizan_version": version,
        "scan_timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "completion_status": "incomplete" if incomplete else "complete",
        "scanner_status": scanner_statuses(scan, incomplete),
        "limitations": [
            "MIZAN ran in read-only mode; this workflow did not repair or modify repository files.",
            "Findings are evidence for independent review, not an automatic approval or merge decision.",
        ],
        "incomplete_sources": incomplete,
        "scan": sanitize(scan),
    }
    envelope["report_digest"] = hashlib.sha256(canonical_json(envelope)).hexdigest()
    encoded = json.dumps(envelope, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    if len(encoded) > MAX_REPORT_BYTES:
        raise ValueError(f"Evidence report exceeds {MAX_REPORT_BYTES} bytes")
    return envelope


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()

    repository = os.environ.get("GITHUB_REPOSITORY", "")
    pr_number = os.environ.get("PR_NUMBER", "")
    head_sha = os.environ.get("PR_HEAD_SHA", "")
    base_sha = os.environ.get("PR_BASE_SHA", "")
    if not repository or not pr_number.isdigit():
        parser.error("GITHUB_REPOSITORY and numeric PR_NUMBER are required")
    if not re.fullmatch(r"[0-9a-f]{40}", head_sha) or not re.fullmatch(r"[0-9a-f]{40}", base_sha):
        parser.error("PR_HEAD_SHA and PR_BASE_SHA must be full 40-character commit SHAs")

    repo_path = Path(args.repo).resolve()
    if not repo_path.is_dir():
        parser.error(f"Repository path is not a directory: {repo_path}")

    with tempfile.TemporaryDirectory(prefix="mizan-pr-evidence-") as temporary:
        raw_path = Path(temporary) / "mizan-full-scan.json"
        command = [
            "mizan", "full-scan", str(repo_path),
            "--jobs", "4", "--output", str(raw_path),
        ]
        completed = subprocess.run(
            command,
            cwd=repo_path,
            check=False,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if completed.stdout:
            print(completed.stdout, end="")
        if completed.stderr:
            print(completed.stderr, file=sys.stderr, end="")
        if not raw_path.is_file():
            print("MIZAN did not produce its full-scan JSON report", file=sys.stderr)
            return 2
        try:
            scan = json.loads(raw_path.read_text(encoding="utf-8"))
            envelope = build_envelope(
                scan=scan,
                repository=repository,
                pr_number=int(pr_number),
                head_sha=head_sha,
                base_sha=base_sha,
                exit_code=completed.returncode,
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            print(f"Evidence contract validation failed: {exc}", file=sys.stderr)
            return 2

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(envelope, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Evidence report: {output}")
    print(f"Completion: {envelope['completion_status']}")
    print(f"Digest: {envelope['report_digest']}")
    return 2 if envelope["completion_status"] == "incomplete" else 0


if __name__ == "__main__":
    raise SystemExit(main())
