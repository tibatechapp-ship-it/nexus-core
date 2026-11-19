"""Mission-level output-token budget contract, persistence and orchestration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.org.contracts import Mission
from src.org.pipeline import MissionPipeline
from src.org.store import OrgError, OrgStore
from src.ops.store import OpsStore


class TestMissionBudgetContract:
    @pytest.mark.parametrize("value", [True, False, 0, -1, "100", 2**63])
    def test_invalid_output_token_limits_are_rejected(self, value: object) -> None:
        with pytest.raises(ValueError, match="output_token_limit"):
            Mission(
                title="bounded", objective="test",
                output_token_limit=value,  # type: ignore[arg-type]
            )

    def test_limit_round_trips_through_dict(self) -> None:
        mission = Mission(title="bounded", objective="test",
                          output_token_limit=25000)
        restored = Mission.from_dict(mission.to_dict())
        assert restored.output_token_limit == 25000


class TestMissionBudgetPersistence:
    def test_create_mission_persists_cap_and_budget_atomically(self) -> None:
        store = OrgStore(":memory:")
        mission = store.create_mission(Mission(
            title="bounded", objective="persist cap", output_token_limit=12000))

        restored = store.mission_get(mission.id)
        budget = store.mission_token_budget_get(mission.id)
        assert restored is not None
        assert restored.output_token_limit == 12000
        assert budget is not None
        assert budget["output_token_limit"] == 12000
        assert budget["reserved_output_tokens"] == 0
        assert budget["consumed_output_tokens"] == 0

    def test_existing_mission_cannot_be_recreated_with_different_cap(self) -> None:
        store = OrgStore(":memory:")
        store.create_mission(Mission(
            title="same identity", objective="immutable", output_token_limit=1000))
        with pytest.raises(OrgError, match="مختلف"):
            store.create_mission(Mission(
                title="same identity", objective="immutable",
                output_token_limit=2000))

    def test_direct_configuration_updates_mission_contract_and_is_immutable(self) -> None:
        store = OrgStore(":memory:")
        mission = store.create_mission(Mission(title="legacy", objective="configure later"))
        store.configure_mission_token_budget(mission.id, 4000)
        restored = store.mission_get(mission.id)
        assert restored is not None
        assert restored.output_token_limit == 4000
        with pytest.raises(OrgError, match="لا يمكن تغييره"):
            store.configure_mission_token_budget(mission.id, 5000)

    def test_mission_updates_do_not_clear_budget_policy(self) -> None:
        store = OrgStore(":memory:")
        mission = store.create_mission(Mission(
            title="running", objective="retain cap", output_token_limit=9000))
        updated = store.mission_update(Mission(
            title=mission.title, objective=mission.objective,
            status="running", id=mission.id))
        assert updated.output_token_limit == 9000

    def test_mission_update_cannot_change_existing_cap(self) -> None:
        store = OrgStore(":memory:")
        mission = store.create_mission(Mission(
            title="immutable", objective="cap", output_token_limit=9000))
        with pytest.raises(OrgError, match="غير قابل للتغيير"):
            store.mission_update(Mission(
                title=mission.title, objective=mission.objective,
                output_token_limit=10000, id=mission.id))

    def test_v8_budget_is_backfilled_into_v9_mission_contract(self, tmp_path: Path) -> None:
        db = tmp_path / "v8-budget.sqlite"
        first = OrgStore(db)
        mission = first.create_mission(Mission(
            title="legacy budget", objective="migration"))
        first.configure_mission_token_budget(mission.id, 7000)
        with first._conn:
            first._conn.execute(
                "UPDATE missions SET output_token_limit=NULL WHERE id=?",
                (mission.id,))
            first._conn.execute(
                "UPDATE meta SET value='8' WHERE key='org_schema_version'")
        first.close()

        migrated = OrgStore(db)
        try:
            restored = migrated.mission_get(mission.id)
            budget = migrated.mission_token_budget_get(mission.id)
            assert restored is not None and restored.output_token_limit == 7000
            assert budget is not None and budget["output_token_limit"] == 7000
        finally:
            migrated.close()

    def test_legacy_mission_remains_unbudgeted(self) -> None:
        store = OrgStore(":memory:")
        mission = store.create_mission(Mission(title="legacy", objective="no cap"))
        assert mission.output_token_limit is None
        assert store.mission_token_budget_get(mission.id) is None


class TestPipelineBudgetLifecycle:
    def test_pipeline_reuses_existing_mission_without_creating_another(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = OrgStore(":memory:")
        mission = store.create_mission(Mission(
            title="existing", objective="retain identity",
            repo_path="fixture", output_token_limit=200000,
        ))
        pipeline = MissionPipeline(
            store, OpsStore(":memory:"), outdir=tmp_path / "reports")
        captured: dict[str, object] = {}

        def fake_execute(candidate: Mission, *, execution_policy: dict[str, object]) -> Mission:
            captured["mission"] = candidate
            captured["policy"] = execution_policy
            return candidate

        monkeypatch.setattr(pipeline.orchestrator, "execute", fake_execute)
        report = pipeline.run(
            title=mission.title, objective=mission.objective,
            repo_path=mission.repo_path,
            output_token_limit=mission.output_token_limit,
            execution_policy={
                "schema_version": 1, "execution_mode": "process",
                "trusted_local": True,
            },
            existing_mission=mission,
        )
        assert report.mission.id == mission.id
        assert captured["mission"].id == mission.id
        assert len(store.mission_list()) == 1

    def test_pipeline_configures_budget_before_agent_work_and_settles_it(
            self, tmp_path: Path) -> None:
        store = OrgStore(":memory:")
        pipeline = MissionPipeline(
            store, OpsStore(":memory:"), outdir=tmp_path / "reports")
        report = pipeline.run(
            title="ميزانية مهمة اختبارية",
            objective=("أضف حارس قسمة على صفر إلى دالة divide في وحدة "
                       "calc.mathops مع اختبارات للحدية"),
            repo_path="examples/org_demo/fixture_repo",
            output_token_limit=200000,
            execution_policy={
                "schema_version": 1, "execution_mode": "process",
                "trusted_local": True,
            },
        )

        assert report.mission.status == "done"
        mission = store.mission_get(report.mission.id)
        budget = store.mission_token_budget_get(report.mission.id)
        assert mission is not None and mission.output_token_limit == 200000
        assert budget is not None
        assert budget["consumed_output_tokens"] > 0
        assert budget["reserved_output_tokens"] == 0
        assert budget["consumed_output_tokens"] <= 200000


def test_cli_exposes_and_validates_mission_output_token_cap() -> None:
    from src.org.cli import build_parser

    parser = build_parser()
    args = parser.parse_args([
        "mission", "--title", "bounded", "--objective", "test",
        "--max-output-tokens", "15000",
        "--execution-mode", "process", "--trust-local",
    ])
    assert args.max_output_tokens == 15000
    with pytest.raises(SystemExit):
        parser.parse_args([
            "mission", "--title", "bounded", "--objective", "test",
            "--max-output-tokens", "0",
        ])
