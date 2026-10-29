"""Deploy-contract tests: the compose stack, the Dockerfile and the probe agree.

These are guardrails, not decoration. Every failure they catch is a deployment
bug that costs a whole rollout:

* a readiness probe reads ``POSTGRES_HOST`` but compose only sets
  ``DATABASE_URL`` → the probe reports "down" forever on a healthy stack,
* a password pasted into ``docker-compose.yml`` → a secret in git history,
* the database port published to the world → an exposed Postgres,
* a backup service pointing at a script that was renamed → nightly backup that
  silently stopped existing.

None of it needs Docker: the files are parsed and cross-checked, so this runs on
the phone exactly like in CI.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
_COMPOSE = _ROOT / "docker-compose.yml"
_DOCKERFILE = _ROOT / "Dockerfile"
_READINESS = _ROOT / "src" / "readiness.py"
_SECRET_KEY = re.compile(r"(PASSWORD|SECRET|TOKEN|API_KEY|PRIVATE)", re.IGNORECASE)


@pytest.fixture(scope="module")
def compose() -> dict:
    assert _COMPOSE.is_file(), "docker-compose.yml is missing"
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def app_env(compose: dict) -> dict:
    return compose["services"]["app"]["environment"]


# ───────────────────────────── compose structure ─────────────────────────────

def test_compose_defines_the_whole_stack(compose: dict) -> None:
    services = compose["services"]
    assert {"app", "postgres", "redis", "backup"} <= set(services)
    assert compose["volumes"].keys() >= {"nexus_data", "nexus_pgdata", "nexus_backups"}


def test_no_secret_is_hardcoded(compose: dict) -> None:
    """Every secret-looking value must be an interpolation, never a literal."""
    offenders = []
    for name, service in compose["services"].items():
        for key, value in (service.get("environment") or {}).items():
            if not _SECRET_KEY.search(key):
                continue
            text = str(value)
            # allowed: ${VAR}, ${VAR:-default}, ${VAR:?message}, or empty
            if text and not text.startswith("${"):
                offenders.append(f"{name}.{key}={text!r}")
    assert not offenders, f"hardcoded secrets in docker-compose.yml: {offenders}"


def test_app_waits_for_healthy_dependencies(compose: dict) -> None:
    depends = compose["services"]["app"]["depends_on"]
    for dep in ("postgres", "redis"):
        assert depends[dep]["condition"] == "service_healthy"
        assert "healthcheck" in compose["services"][dep], f"{dep} has no healthcheck"


def test_databases_are_not_published_to_the_host(compose: dict) -> None:
    for dep in ("postgres", "redis"):
        service = compose["services"][dep]
        assert "ports" not in service, f"{dep} must not publish a host port"
        assert service["expose"], f"{dep} must still be reachable on the compose network"


def test_app_healthcheck_probes_the_health_endpoint(compose: dict) -> None:
    check = compose["services"]["app"]["healthcheck"]
    command = " ".join(check["test"]) if isinstance(check["test"], list) else check["test"]
    assert "/api/health" in command
    assert check["start_period"], "a slow first boot needs a start_period"


def test_app_is_hardened(compose: dict) -> None:
    service = compose["services"]["app"]
    assert service["read_only"] is True
    assert "ALL" in service["cap_drop"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert service["tmpfs"], "a read-only root needs a writable /tmp"


# ───────────────────── probe ↔ compose contract parity ─────────────────────

def test_readiness_env_is_fully_supplied_by_compose(app_env: dict, compose: dict) -> None:
    """Every env var the probe reads must be set by the compose app service.

    This is the failure mode that looks like a code bug: the probe uses
    POSTGRES_HOST, compose wires DATABASE_URL, and /api/ready answers 503 on a
    perfectly healthy stack forever.
    """
    source = _READINESS.read_text(encoding="utf-8")
    # *_URL is the OPTIONAL alternative form (it wins when present). Compose
    # deliberately wires the discrete vars only: a password containing "@" or "#"
    # would silently corrupt a URL, and the probe prefers the URL — so a bad
    # password would poison /api/ready instead of failing loudly at connect.
    referenced = {
        name
        for name in re.findall(r'"(POSTGRES_[A-Z]+|REDIS_[A-Z]+)"', source)
        if not name.endswith("_URL")
    }
    missing = {name for name in referenced if name not in app_env}
    assert not missing, f"src/readiness.py reads {sorted(missing)} but compose does not set it"
    for url_var in ("DATABASE_URL", "REDIS_URL"):
        assert url_var not in app_env, f"{url_var} must stay unset while discrete vars are wired"

    # The host values must be the compose service names, not localhost.
    assert app_env["POSTGRES_HOST"] == "postgres"
    assert app_env["REDIS_HOST"] == "redis"
    # ...and those names must be services that actually exist.
    assert {app_env["POSTGRES_HOST"], app_env["REDIS_HOST"]} <= set(compose["services"])
    # Credentials are shared with the server containers, not duplicated.
    pg = compose["services"]["postgres"]["environment"]
    assert pg["POSTGRES_PASSWORD"] == app_env["POSTGRES_PASSWORD"]
    assert pg["POSTGRES_USER"] == app_env["POSTGRES_USER"]
    redis = compose["services"]["redis"]["environment"]
    assert redis["REDIS_PASSWORD"] == app_env["REDIS_PASSWORD"]


# ─────────────────────────────── Dockerfile ───────────────────────────────

def test_dockerfile_is_multistage_and_nonroot() -> None:
    text = _DOCKERFILE.read_text(encoding="utf-8")
    stages = re.findall(r"^FROM\s+\S+\s+AS\s+(\S+)", text, flags=re.MULTILINE | re.IGNORECASE)
    assert len(stages) >= 2, f"expected a builder + runtime stage, got {stages}"
    runtime = text.split("FROM", 1)[1]
    users = re.findall(r"^USER\s+(\S+)", runtime, flags=re.MULTILINE | re.IGNORECASE)
    assert users, "the runtime image must drop root"
    assert users[-1].lower() not in {"root", "0", "0:0"}, f"runtime runs as {users[-1]}"


def test_dockerfile_healthcheck_matches_the_probe() -> None:
    text = _DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(r"^HEALTHCHECK", text, flags=re.MULTILINE)
    assert "/api/health" in text


def test_dockerfile_installs_the_docker_requirements() -> None:
    text = _DOCKERFILE.read_text(encoding="utf-8")
    assert "requirements-docker.txt" in text
    assert (_ROOT / "requirements-docker.txt").is_file()
    assert (_ROOT / ".dockerignore").is_file(), "no .dockerignore = a 200MB build context"


# ─────────────────────────────── backup ───────────────────────────────

def test_backup_service_runs_an_existing_script(compose: dict) -> None:
    service = compose["services"]["backup"]
    assert service["profiles"] == ["backup"], "backup must not start with the stack"
    entry = service["entrypoint"]
    script_name = entry[-1]
    assert script_name.startswith("/scripts/")
    on_disk = _ROOT / "scripts" / Path(script_name).name
    assert on_disk.is_file(), f"{on_disk} is missing"
    assert on_disk.stat().st_mode & 0o111, f"{on_disk} is not executable"

    # The retention knobs the script reads are configured by the service.
    env = service["environment"]
    assert env["BACKUP_DIR"] == "/backups"
    assert "BACKUP_KEEP_DAYS" in env


def test_backup_script_is_posix_and_verifies_the_dump() -> None:
    script = _ROOT / "scripts" / "backup_db.sh"
    text = script.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh"), "must run under Alpine's busybox sh in the container"
    assert "set -eu" in text
    assert "gzip -t" in text, "an unverified dump is a file that looks like a backup"
    assert "pg_dump" in text
    sh = shutil.which("sh")
    if sh:
        result = subprocess.run([sh, "-n", str(script)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
