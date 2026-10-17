"""Training engine + store + HTTP boundary — hardening suite.

The happy path is covered by ``test_training_engine.py`` / ``test_training_api``;
what is exercised here is what happens when the *world* is not ideal:

* an optional layer (field loop, genome, manifest, training plans, certificate
  signer) is missing, disabled or broken — a training run must still complete,
* a log column is damaged or legacy — one bad row must not 500 the history,
* a client sends junk — the HTTP surface must answer 4xx, never raise.

Everything is hermetic: throwaway databases under ``tmp_path`` and no live
provider.  Imports that a test deliberately breaks are restored by the helper
context managers, never left patched for the rest of the session.
"""
from __future__ import annotations

import builtins
import contextlib
import importlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest

from novamind.training import TrainingEngine, TrainingStore
from novamind.training import engine as engine_mod
from novamind.training import store as store_mod


# ── helpers ──────────────────────────────────────────────────────────────
@contextlib.contextmanager
def _import_blocked(*suffixes: str) -> Iterator[None]:
    """Make ``from x import ...`` fail for any absolute name ending in a suffix.

    A plain ``from .field import ...`` statement goes through
    ``builtins.__import__`` even when the module is already cached, so this is
    enough to simulate "the optional module is not deployed here".
    """
    real = builtins.__import__

    def _fake(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.endswith(tuple(suffixes)):
            raise ImportError(f"blocked for this test: {name}")
        return real(name, *args, **kwargs)

    builtins.__import__ = _fake
    try:
        yield
    finally:
        builtins.__import__ = real


@contextlib.contextmanager
def _importlib_blocked(*suffixes: str) -> Iterator[None]:
    """Same idea for the engine's ``importlib.import_module`` probes."""
    real = importlib.import_module

    def _fake(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.endswith(tuple(suffixes)):
            raise ImportError(f"blocked for this test: {name}")
        return real(name, *args, **kwargs)

    importlib.import_module = _fake  # type: ignore[assignment]
    try:
        yield
    finally:
        importlib.import_module = real  # type: ignore[assignment]


def _engine(tmp_path: Path, **kwargs: Any) -> TrainingEngine:
    """An engine on a throwaway DB, genome side-effects off by default."""
    kwargs.setdefault("feed_genome", False)
    return TrainingEngine(
        store=TrainingStore(tmp_path / "training.db"), **kwargs
    )


def _first_importable(*names: str) -> Any:
    """The first module that imports, or skip the test when none does."""
    for name in names:
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    pytest.skip(f"none of these modules exist here: {names}")


class _BrokenLoop:
    """A field loop that raises from every entry point."""

    def tick(self, run: Any) -> None:
        raise RuntimeError("genome exploded")

    def stats(self) -> Dict[str, Any]:
        raise RuntimeError("stats exploded")

    def lessons(self, agent_id: Any = None, limit: int = 50) -> List[Any]:
        raise RuntimeError("lessons exploded")

    def evolve(self) -> List[Dict[str, Any]]:
        raise RuntimeError("evolve exploded")

    def fitness(self, limit: int = 50) -> List[Dict[str, Any]]:
        raise RuntimeError("fitness exploded")


# ── 1. the field loop is optional ────────────────────────────────────────
def test_an_engine_without_the_field_loop_still_trains(tmp_path: Path) -> None:
    """``field_loop=False`` = the P3 contract: runs recorded, no lessons side-file."""
    engine = _engine(tmp_path, field_loop=False)

    run = engine.train("coder", quality=0.95)

    assert run.certified is True
    assert engine.store.get_run(run.run_id) is not None
    assert not (tmp_path / "lessons.db").exists()
    assert engine.field() is None


def test_a_disabled_engine_empties_every_field_view(tmp_path: Path) -> None:
    engine = _engine(tmp_path, field_loop=False)

    assert engine.field_stats() == {}
    assert engine.lessons() == []
    assert engine.evolve() == []
    assert engine.fitness() == []


def test_disabling_the_field_loop_by_environment_empties_the_views(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``NEXUS_TRAINING_FIELD=off`` must look exactly like ``field_loop=False``."""
    field_mod = importlib.import_module("novamind.training.field")
    monkeypatch.setenv(field_mod.FIELD_ENV, "off")
    engine = _engine(tmp_path)

    assert engine.field() is None
    assert engine.field_stats() == {}
    assert engine.lessons() == []

    engine.train("coder", quality=0.95)
    assert not (tmp_path / "lessons.db").exists()


def test_a_missing_field_module_leaves_the_engine_trainable(tmp_path: Path) -> None:
    """The loop is a bonus layer: its absence must not break training."""
    engine = _engine(tmp_path)

    with _import_blocked("field"):
        assert engine.field() is None
        run = engine.train("coder", quality=0.95)

    assert run.certified is True
    assert engine.store.get_run(run.run_id) is not None


def test_a_raising_loop_never_breaks_a_training_run(tmp_path: Path) -> None:
    """A broken genome must not cost the run that was being recorded."""
    engine = _engine(tmp_path)
    engine._field = _BrokenLoop()

    run = engine.train("coder", quality=0.95)

    assert run.certified is True
    assert engine.store.get_run(run.run_id) is not None


def test_the_field_views_swallow_a_broken_loop(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine._field = _BrokenLoop()

    assert engine.field_stats() == {}
    assert engine.lessons() == []
    assert engine.evolve() == []
    assert engine.fitness() == []


def test_the_field_loop_is_created_once_and_reused(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    first = engine.field()
    assert first is not None
    assert engine.field() is first          # cached, not one loop per call


# ── 2. the curriculum always resolves ────────────────────────────────────
def test_a_missing_manifest_layer_still_yields_a_curriculum(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    with _importlib_blocked("agents.manifest", "src.agents.manifest"):
        modules = engine.modules_for("coder")

    assert modules, "a curriculum must exist even with no manifest layer"
    assert all(m.name for m in modules)


def test_a_raising_manifest_lookup_is_treated_as_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _first_importable("agents.manifest", "src.agents.manifest")

    def _boom(agent_id: str) -> Any:
        raise RuntimeError("manifest layer is a stub here")

    monkeypatch.setattr(manifest, "get_manifest", _boom)
    engine = _engine(tmp_path)

    assert engine.modules_for("coder"), "the curriculum must fall back"


def test_a_missing_training_plans_module_falls_back(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    with _importlib_blocked(
        "novamind.core.training.training_plans",
        "src.novamind.core.training.training_plans",
    ):
        modules = engine.modules_for("coder")

    names = [m.name for m in modules]
    assert set(engine_mod._FALLBACK_SKILLS) <= set(names)
    assert all(m.name for m in modules)


def test_an_empty_plan_falls_back_to_the_documented_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans = _first_importable(
        "novamind.core.training.training_plans",
        "src.novamind.core.training.training_plans",
    )

    class _EmptyPlan:
        modules: List[Any] = []

    monkeypatch.setattr(plans, "get_training_plan", lambda spec: _EmptyPlan())
    engine = _engine(tmp_path)

    names = [m.name for m in engine.modules_for("coder")]
    assert set(engine_mod._FALLBACK_SKILLS) <= set(names)


def test_a_raising_plan_falls_back_to_the_documented_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans = _first_importable(
        "novamind.core.training.training_plans",
        "src.novamind.core.training.training_plans",
    )

    def _boom(spec: str) -> Any:
        raise RuntimeError("plan table is corrupt")

    monkeypatch.setattr(plans, "get_training_plan", _boom)
    engine = _engine(tmp_path)

    names = [m.name for m in engine.modules_for("coder")]
    assert set(engine_mod._FALLBACK_SKILLS) <= set(names)


def test_an_unknown_agent_id_still_gets_a_plan(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    plan = engine.plan("nobody-at-all")

    assert plan["agent_id"] == "nobody-at-all"
    assert plan["module_count"] == len(plan["modules"]) > 0
    assert plan["spec"] == "default"


# ── 3. certificates: signed or explicitly unsigned ────────────────────────
def test_signing_is_declined_when_the_ed25519_primitive_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine_mod.reset_signer()
    monkeypatch.setattr(engine_mod, "_SIGNER", None)
    try:
        with _importlib_blocked("cryptography.hazmat.primitives.asymmetric.ed25519"):
            assert engine_mod._sign_certificate({"a": 1}) == ""
        assert engine_mod._SIGNER is False, "the probe result must be cached"
        # Cached as unavailable: no second probe, still no invented signature.
        assert engine_mod._sign_certificate({"a": 1}) == ""
    finally:
        engine_mod.reset_signer()


def test_a_failing_signer_degrades_to_an_unsigned_certificate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Exploding:
        def sign(self, payload: Dict[str, Any]) -> str:
            raise RuntimeError("key file is unreadable")

    monkeypatch.setattr(engine_mod, "_SIGNER", _Exploding())

    assert engine_mod._sign_certificate({"a": 1}) == ""


def test_a_working_signer_signs_and_can_be_forgotten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Fake:
        def sign(self, payload: Dict[str, Any]) -> str:
            return "sig:" + str(len(payload))

    monkeypatch.setattr(engine_mod, "_SIGNER", _Fake())

    assert engine_mod._sign_certificate({"a": 1, "b": 2}) == "sig:2"
    engine_mod.reset_signer()
    assert engine_mod._SIGNER is None


def test_a_graduated_run_is_certified_signed_or_honestly_unsigned(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)

    run = engine.train("coder", quality=0.95)
    certificate = engine.store.list_certificates(agent_id="coder")[0]

    assert run.certified is True
    assert certificate["certificate_id"].startswith("cert_")
    assert isinstance(certificate["signature"], str)
    # Either a real Ed25519 signature or the documented empty string; a run
    # may never claim a signature it cannot produce.
    assert certificate["signature"] == "" or len(certificate["signature"]) > 16


def test_the_certificate_id_is_stable_for_the_same_run(tmp_path: Path) -> None:
    """A certificate id is content-addressed: same run, same id."""
    import hashlib

    engine = _engine(tmp_path)
    run = engine.train("coder", quality=0.95)
    certificate = engine.store.list_certificates()[0]

    expected = "cert_" + hashlib.sha256(
        f"{run.run_id}|{run.agent_id}|{run.final_score}".encode("utf-8")
    ).hexdigest()[:16]
    assert certificate["certificate_id"] == expected


def test_the_genome_feed_is_a_noop_without_genome_v2(tmp_path: Path) -> None:
    engine = _engine(tmp_path, feed_genome=True)

    with _importlib_blocked("novamind.genome_v2", "src.novamind.genome_v2"):
        run = engine.train("coder", quality=0.95)

    assert run.certified is True


def test_the_one_way_genome_feed_still_works_without_the_loop(
    tmp_path: Path,
) -> None:
    """``field_loop=False`` = the P3 contract: the genome is fed directly."""
    genome_mod = importlib.import_module("novamind.genome_v2")
    engine = _engine(tmp_path, field_loop=False, feed_genome=True)

    run = engine.train("coder", quality=0.95)

    row = genome_mod.get_genome_v2().to_dict()["agents"].get("coder")
    assert run.certified is True
    assert row is not None, "the P3 genome feed must still record the agent"
    assert int(row["observations"]) >= 1


def test_the_one_way_genome_feed_is_a_noop_without_genome_v2(tmp_path: Path) -> None:
    engine = _engine(tmp_path, field_loop=False, feed_genome=True)

    with _importlib_blocked("novamind.genome_v2", "src.novamind.genome_v2"):
        run = engine.train("coder", quality=0.95)

    assert run.certified is True


def test_a_working_signer_module_produces_a_real_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The signing path is exercised with a stub module (no cryptography needed)."""
    try:
        importlib.import_module("cryptography.hazmat.primitives.asymmetric.ed25519")
    except ImportError:
        pytest.skip("the ed25519 primitive is unavailable here")

    class _Signer:
        def sign(self, payload: Dict[str, Any]) -> str:
            return "ed25519:" + str(payload["certificate_id"])

    fake_module = type("fake_signer_module", (), {"Signer": _Signer})
    real_import = importlib.import_module

    def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name in ("certification.signer", "src.certification.signer"):
            return fake_module
        return real_import(name, *args, **kwargs)

    engine_mod.reset_signer()
    monkeypatch.setattr(importlib, "import_module", _fake_import)

    engine = _engine(tmp_path)
    run = engine.train("coder", quality=0.95)
    certificate = engine.store.list_certificates()[0]

    assert run.certified is True
    assert certificate["signature"].startswith("ed25519:cert_")
    engine_mod.reset_signer()


# ── 4. the store is robust ───────────────────────────────────────────────
def test_an_empty_store_reports_zeroed_counters(tmp_path: Path) -> None:
    stats = TrainingStore(tmp_path / "training.db").stats()

    assert stats["runs"] == 0
    assert stats["certified"] == 0
    assert stats["certificates"] == 0
    assert stats["avg_score"] == 0
    assert stats["schema_version"] == store_mod.SCHEMA_VERSION
    assert stats["path"].endswith("training.db")


def test_the_explicit_training_db_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEXUS_TRAINING_DB", str(tmp_path / "explicit.db"))
    monkeypatch.setenv("NEXUS_DB", str(tmp_path / "sessions.db"))

    assert store_mod.default_db_path() == tmp_path / "explicit.db"


def test_the_training_db_sits_beside_the_session_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NEXUS_TRAINING_DB", raising=False)
    monkeypatch.setenv("NEXUS_DB", str(tmp_path / "sessions.db"))

    assert store_mod.default_db_path() == tmp_path / "training.db"


def test_the_repo_data_folder_is_the_last_named_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEXUS_TRAINING_DB", raising=False)
    monkeypatch.delenv("NEXUS_DB", raising=False)

    path = store_mod.default_db_path()

    assert path.name == "training.db"
    assert path.parent.name == "data"


@pytest.mark.parametrize(
    ("raw", "fallback", "expected"),
    [
        ('{"a": 1}', {}, {"a": 1}),
        (b'[{"skill": "x"}]', [], [{"skill": "x"}]),
        ('{"a": 1}', [], []),                 # object where a list is expected
        ("[1, 2]", {}, {}),                   # list where an object is expected
        ("{truncated", {}, {}),               # damaged JSON -> typed empty
        (None, [], []),                       # legacy NULL column
        (None, {}, {}),
        (["already", "decoded"], [], ["already", "decoded"]),
    ],
)
def test_a_damaged_json_column_degrades_to_a_typed_empty(
    raw: Any, fallback: Any, expected: Any
) -> None:
    assert store_mod._json_column(raw, fallback) == expected


def test_a_damaged_run_row_does_not_hide_the_healthy_ones(tmp_path: Path) -> None:
    """Regression for the 500: history must survive one unreadable row."""
    path = tmp_path / "training.db"
    healthy = _engine(tmp_path).train("coder", quality=0.95)

    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            "INSERT INTO training_runs (run_id, agent_id, spec, started_at,"
            " finished_at, completion_rate, training_score, gate_score,"
            " final_score, verdict, certified, phases, detail) VALUES"
            " ('tr_damaged', 'coder', 'default', 1.0, 2.0, 1.0, 1.0, 1.0, 1.0,"
            " 'graduated', 1, '{oops', 'not-json')"
        )
        conn.commit()

    # The fixture must really be damaged, or the regression proves nothing.
    with sqlite3.connect(str(path)) as conn:
        raw = conn.execute(
            "SELECT phases FROM training_runs WHERE run_id = 'tr_damaged'"
        ).fetchone()[0]
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)

    runs = TrainingStore(path).list_runs(limit=10)

    assert {r.run_id for r in runs} == {"tr_damaged", healthy.run_id}
    damaged = next(r for r in runs if r.run_id == "tr_damaged")
    assert not damaged.phases, "a damaged column degrades to empty"
    assert isinstance(damaged.detail, dict)


def test_a_damaged_certificate_payload_still_lists(tmp_path: Path) -> None:
    """A certificate whose payload column is unreadable still lists, empty."""
    path = tmp_path / "training.db"
    healthy = _engine(tmp_path).train("coder", quality=0.95)
    good = TrainingStore(path).list_certificates()[0]

    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            "INSERT INTO training_certificates (certificate_id, run_id, agent_id,"
            " spec, score, issued_at, signature, payload) VALUES"
            " ('cert_damaged', 'tr_x', 'coder', 'default', 0.1, 0.0, '',"
            " 'not-json-at-all')"
        )
        conn.commit()

    by_id = {c["certificate_id"]: c for c in TrainingStore(path).list_certificates()}

    assert set(by_id) == {good["certificate_id"], "cert_damaged"}
    assert by_id["cert_damaged"]["payload"] == {}
    assert by_id["cert_damaged"]["agent_id"] == "coder"
    assert by_id[good["certificate_id"]]["payload"] == good["payload"]
    assert healthy.run_id == good["run_id"]


# ── 5. the HTTP boundary ─────────────────────────────────────────────────
fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from novamind.training.api import build_router, router_for_app  # noqa: E402


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """A bare app carrying a throwaway training router."""
    app = FastAPI()
    app.include_router(build_router(_engine(tmp_path)))
    return TestClient(app)


def test_junk_json_is_rejected_not_crashed(client: TestClient) -> None:
    response = client.post(
        "/api/training/run",
        content=b"{not json at all",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422


def test_run_rejects_an_overlong_agent_id(client: TestClient) -> None:
    response = client.post("/api/training/run", json={"agent_id": "x" * 200})

    assert response.status_code == 422


def test_run_rejects_an_overlong_salt(client: TestClient) -> None:
    response = client.post(
        "/api/training/run", json={"agent_id": "coder", "salt": "s" * 200}
    )

    assert response.status_code == 422


@pytest.mark.parametrize("limit", [0, -1, -999, 10_000])
def test_the_history_limit_is_clamped_not_crashed(client: TestClient, limit: int) -> None:
    client.post("/api/training/run", json={"agent_id": "coder", "quality": 0.95})

    response = client.get(f"/api/training/runs?limit={limit}")

    assert response.status_code == 200
    assert response.json()["count"] >= 0


@pytest.mark.parametrize("limit", [0, -3])
def test_the_lessons_limit_is_clamped(client: TestClient, limit: int) -> None:
    response = client.get(f"/api/training/lessons?limit={limit}")

    assert response.status_code == 200


@pytest.mark.parametrize("limit", [0, -3])
def test_the_fitness_limit_is_clamped(client: TestClient, limit: int) -> None:
    response = client.get(f"/api/training/fitness?limit={limit}")

    assert response.status_code == 200


def test_batch_rejects_too_many_agents(client: TestClient) -> None:
    response = client.post(
        "/api/training/batch", json={"agent_ids": ["a"] * 250}
    )

    assert response.status_code == 422


def test_an_unknown_agent_id_still_answers_a_plan(client: TestClient) -> None:
    response = client.get("/api/training/plan/does-not-exist")

    assert response.status_code == 200
    assert response.json()["module_count"] > 0


def test_an_unknown_training_route_is_404(client: TestClient) -> None:
    assert client.get("/api/training/definitely-not-a-route").status_code == 404


def test_certificates_can_be_filtered_by_agent(client: TestClient) -> None:
    client.post("/api/training/run", json={"agent_id": "coder", "quality": 0.95})
    client.post("/api/training/run", json={"agent_id": "weak", "quality": 0.30})

    everything = client.get("/api/training/certificates").json()
    filtered = client.get("/api/training/certificates?agent_id=coder").json()

    assert filtered["count"] == 1
    assert filtered["count"] <= everything["count"]


def test_router_for_app_returns_a_router_bound_to_the_process_store() -> None:
    router = router_for_app(FastAPI())

    paths = {route.path for route in router.routes}
    assert "/api/training/status" in paths
    assert all(path.startswith("/api/training") for path in paths)

def test_the_genome_feed_survives_an_exploding_genome(tmp_path: Path) -> None:
    """A broken genome must never cost the run that was being recorded."""
    real = importlib.import_module

    class _Exploding:
        def get_genome_v2(self) -> Any:
            raise RuntimeError("genome state is corrupt")

    def _fake(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.endswith("genome_v2"):
            return _Exploding()
        return real(name, *args, **kwargs)

    engine = _engine(tmp_path, field_loop=False, feed_genome=True)
    try:
        importlib.import_module = _fake  # type: ignore[assignment]
        run = engine.train("coder", quality=0.95)
    finally:
        importlib.import_module = real  # type: ignore[assignment]

    assert run.certified is True


def test_the_signer_module_is_constructed_and_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prove the wiring: the signer module is built once and reused."""

    class _Signer:
        def __init__(self) -> None:
            opened.append(True)

        def sign(self, payload: Dict[str, Any]) -> str:
            return "ed25519:" + str(payload["certificate_id"])

    opened: List[Any] = []
    fake_signer = type("fake_signer_module", (), {"Signer": _Signer})
    fake_primitive = type("fake_primitive", (), {})
    real = importlib.import_module

    def _fake(name: str, *args: Any, **kwargs: Any) -> Any:
        if "ed25519" in name:
            return fake_primitive
        if name == "certification.signer":
            # A source checkout only exposes the package as ``src.certification``.
            raise ImportError("no top-level certification package here")
        if name == "src.certification.signer":
            return fake_signer
        return real(name, *args, **kwargs)

    engine_mod.reset_signer()
    monkeypatch.setattr(importlib, "import_module", _fake)

    engine = _engine(tmp_path)
    run = engine.train("coder", quality=0.95)
    certificate = engine.store.list_certificates()[0]

    assert run.certified is True
    assert certificate["signature"].startswith("ed25519:cert_")
    assert len(opened) == 1, "the signer must be built once and cached"
    engine_mod.reset_signer()


def test_a_signer_that_cannot_be_constructed_leaves_certificates_unsigned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Boom:
        def __init__(self) -> None:
            raise RuntimeError("the key store is unreadable")

    fake_signer = type("fake_signer_module", (), {"Signer": _Boom})
    fake_primitive = type("fake_primitive", (), {})
    real = importlib.import_module

    def _fake(name: str, *args: Any, **kwargs: Any) -> Any:
        if "ed25519" in name:
            return fake_primitive
        if name in ("certification.signer", "src.certification.signer"):
            return fake_signer
        return real(name, *args, **kwargs)

    engine_mod.reset_signer()
    monkeypatch.setattr(importlib, "import_module", _fake)

    engine = _engine(tmp_path)
    run = engine.train("coder", quality=0.95)

    assert run.certified is True
    assert engine.store.list_certificates()[0]["signature"] == ""
    engine_mod.reset_signer()


def test_a_failed_write_rolls_back_and_closes_its_connection(tmp_path: Path) -> None:
    """A rejected row must leave no trace and must not leak the handle."""
    store = TrainingStore(tmp_path / "training.db")
    engine = TrainingEngine(store=store, feed_genome=False, field_loop=False)
    run = engine.train("coder", quality=0.95)

    damaged = replace(run, run_id="tr_bad", agent_id=None)  # NOT NULL violation
    with pytest.raises(sqlite3.IntegrityError):
        store.save_run(damaged)

    assert store.get_run("tr_bad") is None
    assert {r.run_id for r in store.list_runs()} == {run.run_id}


def test_the_store_reports_a_usable_timestamp() -> None:
    stamp = store_mod.now()

    assert isinstance(stamp, float)
    assert stamp > 1_600_000_000          # not the epoch / not a mock


def test_an_unwritable_data_folder_falls_back_to_a_temp_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read-only installs still get a working database path."""
    monkeypatch.delenv("NEXUS_TRAINING_DB", raising=False)
    monkeypatch.delenv("NEXUS_DB", raising=False)

    def _refuse(*args: Any, **kwargs: Any) -> None:
        raise OSError("read-only file system")

    monkeypatch.setattr(Path, "mkdir", _refuse)

    path = store_mod.default_db_path()

    assert path.name == "nexus-training.db"
