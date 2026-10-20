"""Tests for the verb-alias expansion layer."""
from __future__ import annotations
import pytest
from src.orchestrator import aliases


def test_expand_adds_implied_words_for_a_known_verb():
    out = aliases.expand({"optimize"})
    assert "performance" in out and "profile" in out
    assert "optimize" in out


def test_expand_leaves_unknown_tokens_untouched():
    out = aliases.expand({"flibbertigibbet", "code"})
    assert "flibbertigibbet" in out
    assert "write" in out  # implied by "code"


@pytest.mark.parametrize(
    "verb,expected",
    [
        ("rotate", "auth"),
        ("deploy", "devops"),
        ("migrate", "schema"),
        ("purge", "remove"),
    ],
)
def test_each_documented_verb_maps_to_its_domain(verb, expected):
    assert expected in aliases.expand({verb})


def test_flag_disables_expansion(monkeypatch):
    monkeypatch.setenv("NEXUS_ALIASES", "0")
    assert aliases.aliases_enabled() is False
    assert aliases.expand({"optimize"}) == {"optimize"}


def test_flag_defaults_on_and_false_values_disable(monkeypatch):
    monkeypatch.delenv("NEXUS_ALIASES", raising=False)
    assert aliases.aliases_enabled() is True
    for value in ("off", "no", "false", "0"):
        monkeypatch.setenv("NEXUS_ALIASES", value)
        assert aliases.aliases_enabled() is False


def test_known_verbs_are_sorted_and_non_empty():
    verbs = aliases.known_verbs()
    assert list(verbs) == sorted(verbs)
    assert "optimize" in verbs and "rotate" in verbs
