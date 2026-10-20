"""Regression — the RiskLevel str-enum contract + its ordering (v1.31.4).

Guards two defects that were fixed together:

* BUG-A/BUG-B — ``(str, Enum)`` leaked ``"RiskLevel.HIGH"`` through ``str()``,
  so ``str(risk) == "high"`` was silently False on every boundary. ``StrEnum``
  makes ``str()`` return the value.
* BUG-C — a bare ``max(subtasks)`` used the enum's inherited ``>`` and mispicked
  the highest risk, letting a HIGH decomposed task skip the jury gate.
"""

from __future__ import annotations

from src.orchestrator.risk import RiskLevel, risk_key


class TestStrEnumContract:
    def test_risk_level_is_str_enum(self) -> None:
        """str() must return the bare value (not "RiskLevel.HIGH")."""
        assert str(RiskLevel.HIGH) == "high"
        assert str(RiskLevel.MED) == "med"
        assert str(RiskLevel.LOW) == "low"

    def test_equality_and_membership_still_work(self) -> None:
        assert RiskLevel.HIGH == "high"
        assert RiskLevel.MED == "med"
        assert str(RiskLevel.MED) in ("low", "med", "high")
        assert RiskLevel("med") is RiskLevel.MED

    def test_values_are_unchanged(self) -> None:
        """The wire contract: the middle level is "med", never "medium"."""
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MED.value == "med"
        assert RiskLevel.HIGH.value == "high"


class TestOrdering:
    def test_bare_max_was_wrong_and_keyed_max_is_right(self) -> None:
        # The exact bug: an unkeyed max on the enum mispicks the highest risk.
        assert max([RiskLevel.HIGH, RiskLevel.LOW, RiskLevel.MED], key=risk_key) is RiskLevel.HIGH
        assert max([RiskLevel.HIGH, RiskLevel.MED], key=risk_key) is RiskLevel.HIGH

    def test_risk_key_is_monotonic(self) -> None:
        assert risk_key(RiskLevel.LOW) < risk_key(RiskLevel.MED) < risk_key(RiskLevel.HIGH)
