"""Regression guard for GHSA-f56c-v883-vx8r in the production container."""
from pathlib import Path


def test_container_fastapi_minimum_is_the_patched_release() -> None:
    root = Path(__file__).resolve().parents[1]
    requirement = next(
        line.strip()
        for line in (root / "requirements-docker.txt").read_text(encoding="utf-8").splitlines()
        if line.strip().lower().startswith("fastapi")
    )
    # GHSA-f56c-v883-vx8r is fixed in 0.163.2; the Dockerfile installs this
    # file directly, so a lower floor can resolve to a vulnerable version.
    assert requirement == "fastapi>=0.163.2,<1"
