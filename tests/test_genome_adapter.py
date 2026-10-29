"""Unit tests for :class:`GenomeV2Adapter` — the v1 API over the v2 store.

The generic behaviour is covered through ``Genome(...)`` delegation in
``test_genome_unification.py``; this file pins the adapter's own surface:
identity derivation, the v1 row projection, the task/judgement channels and the
v1 export/import format.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from src.novamind.genome.adapter import GenomeV2Adapter
from src.novamind.genome.genome import DEFAULT_NAMES, DEFAULT_PERSONAS, Genome
from src.novamind.genome_v2 import GenomeV2


@pytest.fixture()
def adapter() -> GenomeV2Adapter:
    return GenomeV2Adapter(GenomeV2())


# ── identity ──────────────────────────────────────────────────────────────
def test_identity_prefers_the_council_roster(adapter: GenomeV2Adapter) -> None:
    row = adapter.seed(members=[]) or 0
    assert row == 0
    identity = adapter._identity("tork_acil")
    assert identity["name"] == "Tork Acil"
    assert identity["persona"].startswith("أنت «Tork Acil»")
    assert identity["emoji"]


def test_identity_falls_back_to_the_default_personas(adapter: GenomeV2Adapter) -> None:
    # ``analyst`` is both a default persona and a council member; the council
    # roster wins, and it still matches the v1 display name.
    identity = adapter._identity("analyst")
    assert identity["name"] == DEFAULT_NAMES["analyst"]
    assert DEFAULT_NAMES["analyst"] in identity["persona"]
    assert identity["emoji"] == "📊"


def test_identity_uses_the_framework_title_for_class_agents(
    adapter: GenomeV2Adapter,
) -> None:
    identity = adapter._identity("debugger")  # a framework agent, no persona
    assert identity["name"], "a framework manifest title must be used"
    assert identity["persona"] == ""


def test_identity_of_an_unknown_agent_is_its_id(adapter: GenomeV2Adapter) -> None:
    identity = adapter._identity("mystery_agent")
    assert identity == {"name": "mystery_agent", "persona": "", "emoji": ""}


# ── seeding ───────────────────────────────────────────────────────────────
def test_seed_accepts_plain_ids_and_overrides(adapter: GenomeV2Adapter) -> None:
    created = adapter.seed(["alpha", ""], names={"alpha": "Alpha"},
                           personas={"alpha": "the first"})
    assert created == 1                        # the empty id is skipped
    row = adapter.get_agent("alpha")
    assert row is not None
    assert row["name"] == "Alpha"
    assert row["persona"] == "the first"
    assert adapter.seed(["alpha"]) == 0        # idempotent


def test_seed_defaults_to_the_v1_personas(adapter: GenomeV2Adapter) -> None:
    created = adapter.seed()
    assert created == len(DEFAULT_PERSONAS)
    assert adapter.seed() == 0


# ── learning ──────────────────────────────────────────────────────────────
def test_record_folds_quality_and_duration(adapter: GenomeV2Adapter) -> None:
    row = adapter.record("analyst", success=True, latency_ms=2500,
                         detail={"quality": 0.9, "task": "review"})
    assert row["runs"] == 1
    assert row["successes"] == 1
    assert row["latency_avg_ms"] == 2500
    assert row["timeline"], "v2 history must surface as the v1 timeline"
    assert row["task_last_quality"] == pytest.approx(0.9)


def test_record_tolerates_a_broken_quality(adapter: GenomeV2Adapter) -> None:
    row = adapter.record("analyst", success=False, detail={"quality": "n/a"})
    assert row["successes"] == 0
    assert row["failures"] == 1
    assert row["status"] in {"active", "promoted", "probation"}


def test_record_without_detail_uses_the_kind(adapter: GenomeV2Adapter) -> None:
    row = adapter.record("analyst", success=True, kind="manual")
    assert row["task_last_ok"] is True
    assert row["runs"] == 1


def test_outcome_from_influence_maps_the_delta_to_a_stance(
    adapter: GenomeV2Adapter,
) -> None:
    agree = adapter.outcome_from_influence("analyst", 0.8, 2, 0.7, latency_ms=90)
    assert agree["agreements"] == 1
    assert agree["last_latency_ms"] == 90
    dissent = adapter.outcome_from_influence("critic", -1.0, -1, 0.4)
    assert dissent["observations"] == 1
    assert dissent["agreements"] == 0
    assert "last_latency_ms" not in dissent


# ── lifecycle / views ─────────────────────────────────────────────────────
def test_reset_returns_none_for_an_unknown_agent(adapter: GenomeV2Adapter) -> None:
    assert adapter.reset("nobody") is None
    adapter.seed(["analyst"])
    row = adapter.reset("analyst", note="retrain")
    assert row is not None
    assert row["generation"] == 2
    assert row["runs"] == 0


def test_update_agent_writes_only_through_the_api(adapter: GenomeV2Adapter) -> None:
    assert adapter.update_agent("nobody", name="x") is False
    adapter.seed(["analyst"])
    assert adapter.update_agent("analyst", name="المحلل", persona="p",
                                meta={"ui": "blue"}) is True
    row = adapter.get_agent("analyst")
    assert row is not None
    assert (row["name"], row["persona"], row["meta"]["ui"]) == (
        "المحلل", "p", "blue")


def test_detail_adds_advice_and_trims_the_timeline(
    adapter: GenomeV2Adapter,
) -> None:
    assert adapter.detail("nobody") is None
    for _ in range(5):
        adapter.record("analyst", success=True)
    detail = adapter.detail("analyst", timeline_limit=2)
    assert detail is not None
    assert len(detail["timeline"]) == 2
    assert detail["advice"]["action"] in {"promote", "retrain", "retire", "hold",
                                          "keep"}


def test_list_agents_aliases_rank(adapter: GenomeV2Adapter) -> None:
    adapter.seed(["a", "b"])
    assert [r["agent_id"] for r in adapter.list_agents()] == [
        r["agent_id"] for r in adapter.rank()]


def test_fitness_of_is_neutral_for_unknown_agents(adapter: GenomeV2Adapter) -> None:
    assert adapter.fitness_of("nobody") == pytest.approx(0.5)
    adapter.record("analyst", success=True)
    assert adapter.fitness_of("analyst") > 0.5


# ── export / import ───────────────────────────────────────────────────────
def test_export_round_trips_through_a_fresh_genome(adapter: GenomeV2Adapter) -> None:
    adapter.seed(["analyst"])
    adapter.record("analyst", success=True)
    payload = adapter.export()
    assert payload["version"] == 2
    assert set(payload["events"]) == {a["agent_id"] for a in payload["agents"]}

    other = GenomeV2Adapter(GenomeV2())
    assert other.import_(payload) == 1
    assert other.get_agent("analyst") is not None


def test_import_accepts_a_v2_dict_payload(adapter: GenomeV2Adapter) -> None:
    source = GenomeV2()
    Genome(source).record("analyst", success=True)
    payload: Dict[str, Any] = {"agents": source.to_dict()}
    assert adapter.import_(payload) == 1
    assert adapter.import_(source.to_dict()) == 1      # the plain v2 export


def test_import_skips_junk_rows(adapter: GenomeV2Adapter) -> None:
    payload = {"agents": [None, 7, {}, {"agent_id": "  "}, "nope"]}
    assert adapter.import_(payload) == 0
    assert adapter.import_({}) == 0
    assert adapter.import_({"agents": None}) == 0


def test_import_without_runs_carries_no_evidence(adapter: GenomeV2Adapter) -> None:
    """A v1 row with a standing but zero runs proves nothing — stay neutral."""
    assert adapter.import_({"agents": [{"agent_id": "analyst", "standing": 0.8}]}) == 1
    row = adapter.get_agent("analyst")
    assert row is not None
    assert row["runs"] == 0
    assert row["standing"] == pytest.approx(0.5)
    assert row["status"] == "active"


def test_import_ignores_an_unparsable_standing(adapter: GenomeV2Adapter) -> None:
    assert adapter.import_({"agents": [{"agent_id": "analyst",
                                       "runs": 2, "successes": 1,
                                       "standing": "high"}]}) == 1
    row = adapter.get_agent("analyst")
    assert row["standing"] == pytest.approx(0.5)   # success rate, not the junk
    assert row["runs"] == 2


def test_import_carries_name_and_persona_into_meta(adapter: GenomeV2Adapter) -> None:
    adapter.import_({"agents": [{"agent_id": "analyst", "name": "N",
                                 "persona": "P"}]})
    row = adapter.get_agent("analyst")
    assert (row["name"], row["persona"]) == ("N", "P")


def test_update_agent_accepts_a_single_field(adapter: GenomeV2Adapter) -> None:
    adapter.seed(["analyst"])
    assert adapter.update_agent("analyst", meta={"tone": "dry"}) is True
    row = adapter.get_agent("analyst")
    assert row["meta"]["tone"] == "dry"
    assert adapter.update_agent("analyst", persona="only persona") is True
    assert adapter.get_agent("analyst")["persona"] == "only persona"


def test_import_carries_a_name_only_or_a_persona_only(adapter: GenomeV2Adapter) -> None:
    adapter.import_({"agents": [{"agent_id": "alpha", "name": "Alpha"}]})
    adapter.import_({"agents": [{"agent_id": "beta", "persona": "Beta persona"}]})
    alpha = adapter.get_agent("alpha")
    beta = adapter.get_agent("beta")
    assert (alpha["name"], alpha["persona"]) == ("Alpha", "")
    assert beta["name"] == "beta"                 # identity fallback = the id
    assert beta["persona"] == "Beta persona"


def test_seed_copies_the_council_emoji(adapter: GenomeV2Adapter) -> None:
    from src.novamind.council import COUNCIL_MEMBERS

    adapter.seed(members=[m for m in COUNCIL_MEMBERS if m.id == "critic"])
    row = adapter.get_agent("critic")
    assert row["emoji"] == "🔎"
