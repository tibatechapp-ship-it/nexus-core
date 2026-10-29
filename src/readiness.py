"""Readiness probe: is Postgres reachable, is Redis reachable?

`/api/health` answers "the process is alive"; `/api/ready` answers "this process
can actually serve work" — the two questions orchestrators ask separately
(liveness vs readiness). A container whose Postgres is down must stay alive
(so the logs are readable) but must stop receiving traffic, which is exactly
what a 503 from `/api/ready` achieves.

Design rules, in order of importance:

1. **Never raise.** A readiness probe that throws is a probe that reports
   "down" for the wrong reason. Every failure becomes ``ok: False`` + ``error``.
2. **Degrade honestly.** When the real driver is installed (``psycopg`` /
   ``redis``) we use it and probe the protocol. When it is not — the phone has
   no psycopg — we fall back to a TCP connect and say so with ``mode: "tcp"``,
   so a green result never claims more than it proved.
3. **No import cost.** Both drivers are optional at import time; the core
   framework stays stdlib-only (see pyproject's philosophy).

Environment (all optional; a missing value means "not configured", not "down"):

    DATABASE_URL          postgresql://user:pass@host:5432/db  (wins if set)
    POSTGRES_HOST/PORT/USER/PASSWORD/DB
    REDIS_URL             redis://:pass@host:6379/0             (wins if set)
    REDIS_HOST/PORT/PASSWORD/DB
"""
from __future__ import annotations

import os
import socket
import time
from typing import Any, Mapping

_CONNECT_TIMEOUT = 2.0


def _safe_int(value: Any, default: int) -> int:
    """Parse an int from env/config without ever raising (bad input = default)."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


# ───────────────────────────── target resolution ─────────────────────────────

def _postgres_target(env: Mapping[str, str]) -> dict[str, Any]:
    """Where Postgres lives, from DATABASE_URL or the discrete POSTGRES_* vars."""
    url = (env.get("DATABASE_URL") or "").strip()
    if url:
        try:
            from urllib.parse import urlsplit

            parts = urlsplit(url)
            return {
                "host": parts.hostname or "localhost",
                "port": _safe_int(parts.port, 5432),
                "user": parts.username or "",
                "password": parts.password or "",
                "dbname": (parts.path or "/").lstrip("/") or "postgres",
                "source": "DATABASE_URL",
            }
        except Exception:  # malformed URL → fall through to discrete vars
            pass
    return {
        "host": env.get("POSTGRES_HOST", "localhost"),
        "port": _safe_int(env.get("POSTGRES_PORT", "5432"), 5432),
        "user": env.get("POSTGRES_USER", "postgres"),
        "password": env.get("POSTGRES_PASSWORD", ""),
        "dbname": env.get("POSTGRES_DB", "postgres"),
        "source": "POSTGRES_*",
    }


def _redis_target(env: Mapping[str, str]) -> dict[str, Any]:
    url = (env.get("REDIS_URL") or "").strip()
    if url:
        try:
            from urllib.parse import urlsplit

            parts = urlsplit(url)
            return {
                "host": parts.hostname or "localhost",
                "port": _safe_int(parts.port, 6379),
                "password": parts.password or "",
                "db": _safe_int((parts.path or "/0").lstrip("/") or 0, 0),
                "source": "REDIS_URL",
            }
        except Exception:
            pass
    return {
        "host": env.get("REDIS_HOST", "localhost"),
        "port": _safe_int(env.get("REDIS_PORT", "6379"), 6379),
        "password": env.get("REDIS_PASSWORD", ""),
        "db": _safe_int(env.get("REDIS_DB", "0"), 0),
        "source": "REDIS_*",
    }


def _optional_import(name: str) -> Any:
    """Import an optional driver, or return ``None`` — a probe must never raise."""
    try:
        return __import__(name)
    except Exception:
        return None


def _elapsed_ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 1)


def _tcp_probe(host: str, port: int, timeout: float = _CONNECT_TIMEOUT) -> None:
    """Raise if a TCP connection cannot be opened. Used as the driverless path."""
    with socket.create_connection((host, port), timeout=timeout):
        return


# ─────────────────────────────── Postgres ───────────────────────────────

def check_postgres(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """TCP reachability first, then ``SELECT 1`` when psycopg is installed.

    The TCP gate comes first on purpose: a refused connection is instant, while
    an authenticated driver connect can spend seconds retrying. A probe must
    answer fast enough for a Kubernetes readiness check to be useful.
    """
    env = os.environ if env is None else env
    target = _postgres_target(env)
    host, port = target["host"], target["port"]
    result: dict[str, Any] = {"name": "postgres", "target": f"{host}:{port}", "mode": "tcp"}
    start = time.monotonic()
    try:
        _tcp_probe(host, port)
    except Exception as exc:  # noqa: BLE001 — a probe must never raise
        result.update(ok=False, error=f"{type(exc).__name__}: {exc}")
        result["latency_ms"] = _elapsed_ms(start)
        return result

    try:
        psycopg = _optional_import("psycopg")
        if psycopg is None:
            result.update(ok=True, detail="driver absent: TCP connect only")
        else:
            result["mode"] = "driver"
            conninfo = (
                f"host={host} port={port} dbname={target['dbname']} "
                f"user={target['user']} password={target['password']} "
                f"connect_timeout={int(_CONNECT_TIMEOUT)}"
            )
            with psycopg.connect(conninfo, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            result.update(ok=True, detail="SELECT 1")
    except Exception as exc:  # noqa: BLE001 — a probe must never raise
        result.update(ok=False, error=f"{type(exc).__name__}: {exc}")
    result["latency_ms"] = _elapsed_ms(start)
    return result


# ──────────────────────────────── Redis ────────────────────────────────

def check_redis(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """TCP reachability first, then ``PING`` when the redis client is installed."""
    env = os.environ if env is None else env
    target = _redis_target(env)
    host, port = target["host"], target["port"]
    result: dict[str, Any] = {"name": "redis", "target": f"{host}:{port}", "mode": "tcp"}
    start = time.monotonic()
    try:
        _tcp_probe(host, port)
    except Exception as exc:  # noqa: BLE001 — a probe must never raise
        result.update(ok=False, error=f"{type(exc).__name__}: {exc}")
        result["latency_ms"] = _elapsed_ms(start)
        return result

    try:
        redis = _optional_import("redis")
        if redis is None:
            result.update(ok=True, detail="driver absent: TCP connect only")
        else:
            result["mode"] = "driver"
            client = redis.Redis(
                host=host,
                port=port,
                password=target["password"] or None,
                db=target["db"],
                socket_connect_timeout=_CONNECT_TIMEOUT,
                socket_timeout=_CONNECT_TIMEOUT,
                retry_on_timeout=False,
            )
            try:
                client.ping()
            finally:
                client.close()
            result.update(ok=True, detail="PING")
    except Exception as exc:  # noqa: BLE001 — a probe must never raise
        result.update(ok=False, error=f"{type(exc).__name__}: {exc}")
    result["latency_ms"] = _elapsed_ms(start)
    return result


# ─────────────────────────────── aggregate ───────────────────────────────

def readiness(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Full readiness payload: ``{ready, checks[], version}``.

    ``ready`` is true only when every dependency answered. The HTTP layer turns
    that into 200/503; the body stays identical so a failing probe is readable
    from the logs without a second call.
    """
    env = os.environ if env is None else env
    checks = [check_postgres(env), check_redis(env)]
    ready = all(c.get("ok") for c in checks)
    return {
        "ready": ready,
        "status": "ready" if ready else "not_ready",
        "checks": checks,
        "version": _app_version(),
    }


def _app_version() -> str:
    """Version from pyproject.toml (single source of truth), never hardcoded."""
    try:
        import tomllib

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "pyproject.toml"), "rb") as fh:
            return str(tomllib.load(fh)["project"]["version"])
    except Exception:
        return "unknown"
