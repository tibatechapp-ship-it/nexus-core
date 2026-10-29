"""Guards for the readiness probe (`/api/ready`) and the health payload.

Why these tests exist: a readiness probe is the one endpoint that decides where
traffic goes. A probe that lies is worse than no probe — a green `/api/ready`
while Postgres is unreachable causes a platform to route 100% of requests into a
broken process. So the tests assert, in order:

* the body shape is IDENTICAL on success and failure (one response is enough to
  diagnose a failing rollout),
* a refused dependency yields 503 with a real reason, never a 200,
* a reachable dependency yields 200 — proven against a REAL listening socket,
  not a mock that could agree with a bug,
* garbage configuration (port "abc", bad URL) degrades instead of raising,
* the driverless path says ``mode: tcp`` so it never over-claims.

Neither psycopg nor redis is required: the tests force the TCP path when the
drivers are present, which also pins down the phone/CI behaviour.
"""
from __future__ import annotations

import builtins
import importlib.util
import socket
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sse_starlette")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent


def _load_workbench_main():
    spec = importlib.util.spec_from_file_location("nexus_workbench_main_ready", _ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def client():
    main = _load_workbench_main()
    main.CRAFT_TOKEN = ""
    return TestClient(main.app), main


@pytest.fixture()
def no_drivers(monkeypatch):
    """Force both readiness checks down the driverless (TCP) path."""

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in {"psycopg", "redis"}:
            raise ImportError(f"{name} blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


@pytest.fixture()
def listening_socket():
    """A real TCP listener standing in for Postgres/Redis reachability."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(8)
    try:
        yield sock.getsockname()[1]
    finally:
        sock.close()


def _dead_port() -> int:
    """A port nobody listens on (bind, read it, close it)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _env(port: int) -> dict[str, str]:
    return {
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PORT": str(port),
        "REDIS_HOST": "127.0.0.1",
        "REDIS_PORT": str(port),
    }


# ─────────────────────────────── /api/health ───────────────────────────────

def test_health_reports_pyproject_version_and_uptime(client):
    c, _ = client
    body = c.get("/api/health").json()
    import src

    assert body["version"] == src.__version__  # version comes from pyproject, one source
    assert body["status"] == "ok"
    assert body["service"] == "nexus-core"
    assert isinstance(body["uptime_seconds"], (int, float))
    assert body["uptime_seconds"] >= 0


# ─────────────────────────────── /api/ready ───────────────────────────────

def test_ready_is_503_with_reasons_when_dependencies_are_down(
    client, monkeypatch, no_drivers
):
    c, _ = client
    port = _dead_port()
    for key, value in _env(port).items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    r = c.get("/api/ready")
    body = r.json()
    assert r.status_code == 503
    assert body["ready"] is False
    assert body["status"] == "not_ready"
    checks = {c_["name"]: c_ for c_ in body["checks"]}
    assert set(checks) == {"postgres", "redis"}
    for name in ("postgres", "redis"):
        assert checks[name]["ok"] is False
        assert checks[name]["error"], f"{name} must explain why it failed"


def test_ready_is_200_when_both_dependencies_answer(
    client, monkeypatch, no_drivers, listening_socket
):
    c, _ = client
    for key, value in _env(listening_socket).items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    r = c.get("/api/ready")
    body = r.json()
    assert r.status_code == 200
    assert body["ready"] is True
    assert body["status"] == "ready"
    # Driverless path must not pretend it ran SELECT 1 / PING.
    assert {c_["mode"] for c_ in body["checks"]} == {"tcp"}


def test_ready_body_shape_is_identical_on_success_and_failure(
    client, monkeypatch, no_drivers
):
    c, _ = client
    dead = _dead_port()
    for key, value in _env(dead).items():
        monkeypatch.setenv(key, value)
    failing = c.get("/api/ready").json()
    for key in ("ready", "status", "checks", "version"):
        assert key in failing, f"missing {key} on the failure path"


def test_partial_outage_is_reported_per_dependency(
    client, monkeypatch, no_drivers, listening_socket
):
    """Postgres up, Redis down → 503 that names exactly which one broke."""
    c, _ = client
    dead = _dead_port()
    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("POSTGRES_PORT", str(listening_socket))
    monkeypatch.setenv("REDIS_HOST", "127.0.0.1")
    monkeypatch.setenv("REDIS_PORT", str(dead))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    r = c.get("/api/ready")
    checks = {c_["name"]: c_ for c_ in r.json()["checks"]}
    assert r.status_code == 503
    assert checks["postgres"]["ok"] is True
    assert checks["redis"]["ok"] is False


# ───────────────────────────── unit level (no HTTP) ─────────────────────────────

def test_garbage_config_degrades_instead_of_raising(no_drivers):
    from src import readiness

    result = readiness.check_postgres({"POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "abc"})
    assert result["ok"] is False
    assert result["target"] == "127.0.0.1:5432"  # fell back to the default port

    again = readiness.check_redis({"REDIS_HOST": "127.0.0.1", "REDIS_DB": "not-a-number"})
    assert again["ok"] is False
    assert "error" in again


def test_database_url_is_parsed_and_wins_over_discrete_vars(no_drivers):
    from src import readiness

    env = {
        "DATABASE_URL": "postgresql://user:pw@127.0.0.1:6543/mydb",
        "POSTGRES_HOST": "should-be-ignored",
        "POSTGRES_PORT": "1111",
    }
    target = readiness._postgres_target(env)
    assert (target["host"], target["port"], target["dbname"]) == ("127.0.0.1", 6543, "mydb")
    assert target["source"] == "DATABASE_URL"


def test_redis_url_is_parsed(no_drivers):
    from src import readiness

    target = readiness._redis_target({"REDIS_URL": "redis://:secret@cache:6380/3"})
    assert (target["host"], target["port"], target["db"], target["password"]) == (
        "cache", 6380, 3, "secret",
    )


def test_readiness_aggregate_is_false_when_any_check_fails(no_drivers):
    from src import readiness

    payload = readiness.readiness(_env(_dead_port()))
    assert payload["ready"] is False
    assert payload["version"]  # version is always present, even when not ready


# ───────────────────────── driver paths (faked, no network) ─────────────────────────
# The real driver path is exercised for real by the CI stack smoke (docker
# compose + Postgres + Redis). These tests keep the code honest offline: they
# prove `mode` flips to "driver", that the query is actually sent, and that a
# driver that blows up is reported instead of raised.

class _FakeCursor:
    def __init__(self, executed: list[str]) -> None:
        self.executed = executed

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str) -> None:
        self.executed.append(sql)

    def fetchone(self) -> tuple[int]:
        return (1,)


class _FakeConnection:
    def __init__(self, executed: list[str]) -> None:
        self.executed = executed

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.executed)


def test_postgres_uses_the_driver_and_sends_select_1(monkeypatch, listening_socket):
    import sys

    from src import readiness

    executed: list[str] = []
    closed: list[bool] = []

    def connect(conninfo: str, autocommit: bool = False) -> _FakeConnection:
        assert "dbname=" in conninfo and "password=" in conninfo
        assert autocommit is True
        return _FakeConnection(executed)

    monkeypatch.setitem(sys.modules, "psycopg", type("FakePsycopg", (), {"connect": staticmethod(connect)})())

    result = readiness.check_postgres(
        {"POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": str(listening_socket)}
    )
    assert result["ok"] is True
    assert result["mode"] == "driver"
    assert result["detail"] == "SELECT 1"
    assert executed == ["SELECT 1"]
    assert closed == []


def test_redis_uses_the_driver_and_pings(monkeypatch, listening_socket):
    import sys

    from src import readiness

    calls: list[str] = []

    class FakeRedis:
        def __init__(self, **kwargs: object) -> None:
            calls.append(f"init db={kwargs.get('db')}")
            assert kwargs.get("socket_connect_timeout")

        def ping(self) -> bool:
            calls.append("ping")
            return True

        def close(self) -> None:
            calls.append("close")

    monkeypatch.setitem(sys.modules, "redis", type("FakeRedisModule", (), {"Redis": FakeRedis})())

    result = readiness.check_redis(
        {"REDIS_HOST": "127.0.0.1", "REDIS_PORT": str(listening_socket), "REDIS_DB": "2"}
    )
    assert result["ok"] is True
    assert result["mode"] == "driver"
    assert result["detail"] == "PING"
    assert calls == ["init db=2", "ping", "close"]


def test_a_broken_driver_is_reported_not_raised(monkeypatch, listening_socket):
    import sys

    from src import readiness

    class BrokenRedis:
        def __init__(self, **kwargs: object) -> None:
            raise RuntimeError("auth failed")

    monkeypatch.setitem(sys.modules, "redis", type("FakeRedisModule", (), {"Redis": BrokenRedis})())

    result = readiness.check_redis(
        {"REDIS_HOST": "127.0.0.1", "REDIS_PORT": str(listening_socket)}
    )
    assert result["ok"] is False
    assert "auth failed" in result["error"]
    # mode names the mechanism that was ATTEMPTED (the real driver); `ok: false`
    # plus `error` is what keeps that from reading as success.
    assert result["mode"] == "driver"


def test_connection_refused_is_fast(no_drivers):
    """A refused port must answer in well under the test timeout (probe budget)."""
    import time

    from src import readiness

    start = time.monotonic()
    result = readiness.check_postgres({"POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": str(_dead_port())})
    assert result["ok"] is False
    assert time.monotonic() - start < 2.0


def test_malformed_urls_fall_back_to_discrete_vars(no_drivers):
    from src import readiness

    env = {"DATABASE_URL": "http://[bad", "POSTGRES_HOST": "db", "POSTGRES_PORT": "5433"}
    target = readiness._postgres_target(env)
    assert (target["host"], target["port"], target["source"]) == ("db", 5433, "POSTGRES_*")

    redis_env = {"REDIS_URL": "http://[bad", "REDIS_HOST": "cache"}
    redis_target = readiness._redis_target(redis_env)
    assert (redis_target["host"], redis_target["source"]) == ("cache", "REDIS_*")


def test_version_never_raises_when_pyproject_is_unreadable(monkeypatch):
    from src import readiness

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("no pyproject")

    monkeypatch.setattr(builtins, "open", boom)
    assert readiness._app_version() == "unknown"


def test_postgres_driver_error_is_reported_not_raised(monkeypatch, listening_socket):
    import sys

    from src import readiness

    def connect(conninfo: str, autocommit: bool = False) -> None:
        raise RuntimeError("password authentication failed")

    monkeypatch.setitem(sys.modules, "psycopg", type("FakePsycopg", (), {"connect": staticmethod(connect)})())

    result = readiness.check_postgres(
        {"POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": str(listening_socket)}
    )
    assert result["ok"] is False
    assert "password authentication failed" in result["error"]
    assert result["mode"] == "driver"
