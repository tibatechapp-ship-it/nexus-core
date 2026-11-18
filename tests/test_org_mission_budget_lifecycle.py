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
        )

        assert report.mission.status == "done"
        mission = store.mission_get(report.mission.id)
        budget = store.mission_token_budget_get(report.mission.id)
        assert mission is not None and mission.output_token_limit == 200000
        assert budget is not None
        assert budget["consumed_output_tokens"] > 0
        assert budget["reserved_output_tokens"] == 0
        assert budget["consumed_output_tokens"] <= 200000



class TestTokenReservationCrashReconciliation:
    def _reserved(self) -> tuple[OrgStore, str, str]:
        store = OrgStore(":memory:")
        mission = store.create_mission(Mission(
            title="crash recovery", objective="reconcile uncertain provider call"))
        store.configure_mission_token_budget(mission.id, 5000)
        reservation = store.reserve_mission_output_tokens(
            mission.id, "agent:backend", 1200)
        return store, mission.id, str(reservation["id"])

    def test_settlement_rolls_back_when_budget_reservation_is_inconsistent(self) -> None:
        store, mission_id, reservation_id = self._reserved()
        with store._conn:
            store._conn.execute(
                "UPDATE mission_token_budgets SET reserved_output_tokens=0 "
                "WHERE mission_id=?", (mission_id,))
        with pytest.raises(OrgError, match="رصيد الحجز غير متسق"):
            store.settle_mission_output_tokens(reservation_id, 100)
        reservation = store._conn.execute(
            "SELECT status FROM mission_token_reservations WHERE id=?",
            (reservation_id,),
        ).fetchone()
        assert reservation["status"] == "reserved"
        store.close()

    def test_release_rolls_back_when_budget_reservation_is_inconsistent(self) -> None:
        store, mission_id, reservation_id = self._reserved()
        with store._conn:
            store._conn.execute(
                "UPDATE mission_token_budgets SET reserved_output_tokens=0 "
                "WHERE mission_id=?", (mission_id,))
        with pytest.raises(OrgError, match="رصيد الحجز غير متسق"):
            store.release_mission_output_tokens(
                reservation_id, "provider confirmed not dispatched")
        reservation = store._conn.execute(
            "SELECT status FROM mission_token_reservations WHERE id=?",
            (reservation_id,),
        ).fetchone()
        assert reservation["status"] == "reserved"
        store.close()

    def test_reconciliation_requires_terminal_provider_confirmation(self) -> None:
        store, mission_id, reservation_id = self._reserved()
        with pytest.raises(OrgError, match="نهائية طلب المزوّد"):
            store.reconcile_mission_output_tokens(
                reservation_id, 0, actor="operator", reason="worker crashed",
                evidence_refs=["incident://worker-42"],
                confirm_provider_terminal=False,
            )
        reservation = store._conn.execute(
            "SELECT status FROM mission_token_reservations WHERE id=?",
            (reservation_id,),
        ).fetchone()
        budget = store.mission_token_budget_get(mission_id)
        assert reservation["status"] == "reserved"
        assert budget is not None and budget["reserved_output_tokens"] == 1200
        store.close()

    def test_reconciliation_settles_once_and_preserves_audit_evidence(self) -> None:
        store, mission_id, reservation_id = self._reserved()
        settled = store.reconcile_mission_output_tokens(
            reservation_id, 375, actor="incident-commander",
            reason="provider request confirmed terminal; usage recovered",
            evidence_refs=["provider-log://req-abc", "trace://worker-42"],
            confirm_provider_terminal=True,
        )
        assert settled["status"] == "settled"
        assert settled["actual_tokens"] == 375
        budget = store.mission_token_budget_get(mission_id)
        assert budget is not None
        assert budget["reserved_output_tokens"] == 0
        assert budget["consumed_output_tokens"] == 375
        record = store._conn.execute(
            "SELECT * FROM mission_token_reconciliations WHERE reservation_id=?",
            (reservation_id,),
        ).fetchone()
        assert record is not None
        assert record["actor"] == "incident-commander"
        assert record["provider_terminal"] == 1
        assert record["actual_tokens"] == 375
        with pytest.raises(OrgError, match="تمت تسويته"):
            store.reconcile_mission_output_tokens(
                reservation_id, 375, actor="incident-commander",
                reason="duplicate attempt", evidence_refs=["provider-log://req-abc"],
                confirm_provider_terminal=True,
            )
        with pytest.raises(Exception, match="immutable"):
            with store._conn:
                store._conn.execute(
                    "UPDATE mission_token_reconciliations SET reason='tampered' "
                    "WHERE reservation_id=?", (reservation_id,))
        store.close()

    def test_reconciliation_rejects_usage_above_reserved_ceiling(self) -> None:
        store, mission_id, reservation_id = self._reserved()
        with pytest.raises(OrgError, match="يتجاوز سقف الحجز"):
            store.reconcile_mission_output_tokens(
                reservation_id, 1201, actor="operator", reason="bad usage",
                evidence_refs=["provider-log://req-abc"],
                confirm_provider_terminal=True,
            )
        budget = store.mission_token_budget_get(mission_id)
        assert budget is not None and budget["reserved_output_tokens"] == 1200
        store.close()

    def test_reconciliation_rejects_oversized_evidence(self) -> None:
        store, mission_id, reservation_id = self._reserved()
        with pytest.raises(OrgError, match="حجم أدلة المصالحة"):
            store.reconcile_mission_output_tokens(
                reservation_id, 0, actor="operator", reason="evidence too large",
                evidence_refs=["x" * 512 for _ in range(32)],
                confirm_provider_terminal=True,
            )
        budget = store.mission_token_budget_get(mission_id)
        assert budget is not None and budget["reserved_output_tokens"] == 1200
        store.close()

    def test_reconciliation_rolls_back_on_inconsistent_budget(self) -> None:
        store, mission_id, reservation_id = self._reserved()
        with store._conn:
            store._conn.execute(
                "UPDATE mission_token_budgets SET reserved_output_tokens=0 "
                "WHERE mission_id=?", (mission_id,))
        with pytest.raises(OrgError, match="رصيد الحجز غير متسق"):
            store.reconcile_mission_output_tokens(
                reservation_id, 100, actor="operator", reason="provider terminal",
                evidence_refs=["provider-log://req-abc"],
                confirm_provider_terminal=True,
            )
        reservation = store._conn.execute(
            "SELECT status FROM mission_token_reservations WHERE id=?",
            (reservation_id,),
        ).fetchone()
        reconciliation_count = store._conn.execute(
            "SELECT COUNT(*) AS n FROM mission_token_reconciliations"
        ).fetchone()["n"]
        assert reservation["status"] == "reserved"
        assert reconciliation_count == 0
        store.close()

    def test_schema_v10_migration_is_idempotent(self, tmp_path: Path) -> None:
        db = tmp_path / "token-reconcile.sqlite"
        first = OrgStore(db)
        assert first._conn.execute(
            "SELECT value FROM meta WHERE key='org_schema_version'"
        ).fetchone()["value"] == "10"
        first.close()
        second = OrgStore(db)
        try:
            assert second._conn.execute(
                "SELECT value FROM meta WHERE key='org_schema_version'"
            ).fetchone()["value"] == "10"
            tables = {row["name"] for row in second._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            assert "mission_token_reconciliations" in tables
        finally:
            second.close()


def test_cli_exposes_and_validates_mission_output_token_cap() -> None:
    from src.org.cli import build_parser

    parser = build_parser()
    args = parser.parse_args([
        "mission", "--title", "bounded", "--objective", "test",
        "--max-output-tokens", "15000",
    ])
    assert args.max_output_tokens == 15000
    with pytest.raises(SystemExit):
        parser.parse_args([
            "mission", "--title", "bounded", "--objective", "test",
            "--max-output-tokens", "0",
        ])
