"""Risk classification tests."""
from src.orchestrator.risk import classify, explain, RiskLevel


def test_delete_genome_is_high():
    assert classify("delete genome.json") == RiskLevel.HIGH


def test_add_docstring_is_low():
    assert classify("add docstring to foo") == RiskLevel.LOW


def test_modify_is_med_by_default():
    assert classify("modify the coder module") == RiskLevel.MED


def test_empty_is_med_failsafe():
    assert classify("") == RiskLevel.MED
    assert classify(None) == RiskLevel.MED
    assert classify("   ") == RiskLevel.MED


def test_high_beats_low():
    assert classify("add comment then deploy") == RiskLevel.HIGH


def test_explain_reports_matches():
    info = explain("delete production auth")
    assert info["level"] == "high"
    assert "delete" in info["matched_high"]
    assert info["reason"].startswith("high:")
