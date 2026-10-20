"""End-to-end routing tests for the alias layer (router + risk together)."""
from __future__ import annotations
from src.orchestrator.router import route, route_with_reason
from src.orchestrator.risk import RiskLevel, classify


def test_destructive_verb_routes_to_an_ops_agent():
    assert route("delete genome entries") in {"recovery", "devops"}


def test_security_verb_routes_to_the_auditor():
    assert route("rotate auth token") == "security_auditor"


def test_token_alone_is_not_high_risk():
    # "token" used as a plain noun (search/overlap) must not trip the HIGH gate
    assert classify("token overlap search") is RiskLevel.MED
    assert classify("tokens") is RiskLevel.MED


def test_token_with_a_destructive_verb_stays_high():
    assert classify("delete the token") is RiskLevel.HIGH
    assert classify("rotate the token secret") is RiskLevel.HIGH


def test_performance_verb_beats_the_zero_score_tie():
    result = route_with_reason("optimize the token overlap search")
    assert result["agent"] == "performance"
    assert result["score"] > 0.0


def test_aliases_off_restores_zero_score_tie(monkeypatch):
    monkeypatch.setenv("NEXUS_ALIASES", "0")
    result = route_with_reason("optimize the token overlap search")
    # without expansion the verb "optimize" no longer reaches performance
    assert result["agent"] != "performance"
