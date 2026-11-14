"""Tests for the MIZAN PR evidence contract."""

import hashlib
import unittest

from scripts.mizan.build_pr_evidence import (
    REQUIRED_SCANNERS,
    build_envelope,
    canonical_json,
)


def complete_scan():
    scan = {
        "engine": "MIZAN Security Master Engine",
        "version": "0.16.0-dev",
        "repository": "/workspace/repo",
        "mode": "read-only",
        "execution_performed": False,
        "scanners_failed": [],
    }
    for name in REQUIRED_SCANNERS:
        scan[name] = {"findings": []}
    scan["analysis"]["custom_rules_errors"] = []
    scan["dependencies"]["osv_errors"] = []
    scan["dependencies"]["osv_unchecked"] = []
    return scan


class EvidenceContractTests(unittest.TestCase):
    def build(self, scan, exit_code=0):
        return build_envelope(
            scan=scan,
            repository="tibatechapp-ship-it/nexus-core",
            pr_number=42,
            head_sha="a" * 40,
            base_sha="b" * 40,
            exit_code=exit_code,
            timestamp="2026-11-14T20:00:00+00:00",
        )

    def test_complete_scan_is_bound_to_pr_sha_and_digest(self):
        report = self.build(complete_scan())
        self.assertEqual(report["schema_version"], "nexus.security-evidence.v1")
        self.assertEqual(report["completion_status"], "complete")
        self.assertEqual(report["head_sha"], "a" * 40)
        digest = report.pop("report_digest")
        self.assertEqual(hashlib.sha256(canonical_json(report)).hexdigest(), digest)

    def test_failed_scanner_makes_report_incomplete(self):
        scan = complete_scan()
        scan["scanners_failed"] = ["git"]
        scan["git"] = {"error": "not available", "findings": []}
        report = self.build(scan, exit_code=2)
        self.assertEqual(report["completion_status"], "incomplete")
        self.assertIn("git", report["incomplete_sources"])

    def test_exit_code_must_match_completeness(self):
        scan = complete_scan()
        scan["scanners_failed"] = ["git"]
        scan["git"] = {"error": "failed", "findings": []}
        with self.assertRaisesRegex(ValueError, "contradicts"):
            self.build(scan, exit_code=0)

    def test_non_read_only_report_is_rejected(self):
        scan = complete_scan()
        scan["execution_performed"] = True
        with self.assertRaisesRegex(ValueError, "read-only"):
            self.build(scan)

    def test_missing_scanner_section_cannot_be_certified_complete(self):
        scan = complete_scan()
        del scan["documentation"]
        report = self.build(scan, exit_code=2)
        self.assertEqual(report["completion_status"], "incomplete")
        self.assertIn("documentation-missing", report["incomplete_sources"])

    def test_credential_fields_are_redacted(self):
        scan = complete_scan()
        scan["analysis"]["api_key"] = "very-secret-value-12345"
        scan["analysis"]["example"] = "ghp_abcdefghijklmnopqrstuvwxyz123456"
        report = self.build(scan)
        self.assertEqual(report["scan"]["analysis"]["api_key"], "[REDACTED]")
        self.assertIn("[REDACTED]", report["scan"]["analysis"]["example"])


if __name__ == "__main__":
    unittest.main()
