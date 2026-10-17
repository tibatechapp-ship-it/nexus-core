"""Tests for ``src/skills/api.py`` — the ``/api/skills/*`` HTTP surface.

Skipped cleanly when FastAPI is absent. Routes are added by hand (``register``),
NOT via a deferred ``include_router`` — so one test drives them through an ASGI
``mount``, the same shape the unified gateway uses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.skills.api import build_router, register  # noqa: E402
from src.skills.loader import SkillLoader  # noqa: E402


@pytest.fixture()
def loader(tmp_path: Path) -> SkillLoader:
    seed = tmp_path / "seed"
    sl = SkillLoader(base_dir=tmp_path / "user", seed_dir=seed)
    (seed / "alpha").mkdir(parents=True, exist_ok=True)
    (seed / "alpha" / "SKILL.md").write_text("# Alpha Skill\n\nrules a\n", encoding="utf-8")
    return sl


@pytest.fixture()
def client(loader: SkillLoader) -> Iterator[TestClient]:
    app = FastAPI()
    register(app, loader)
    with TestClient(app) as c:
        yield c


def test_list_reports_count_and_rows(client: TestClient) -> None:
    """The seeded skills plus the repo seed are all listed, content-free."""
    body = client.get("/api/skills").json()
    assert body["count"] == len(body["skills"]) >= 1
    assert any(s["name"] == "alpha" for s in body["skills"])
    assert "content" not in body["skills"][0]
    assert body["sources"]


def test_detail_returns_content(client: TestClient) -> None:
    body = client.get("/api/skills/alpha").json()
    assert body["name"] == "alpha"
    assert body["description"] == "Alpha Skill"
    assert body["content"] == "# Alpha Skill\n\nrules a\n"


def test_missing_skill_is_404(client: TestClient) -> None:
    assert client.get("/api/skills/nope").status_code == 404


def test_a_listed_but_unloadable_name_is_skipped(
    loader: SkillLoader, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A name that vanishes between listing and loading is skipped, not fatal."""
    monkeypatch.setattr(loader, "list_skills", lambda: ["ghost", "alpha"])
    app = FastAPI()
    register(app, loader)
    with TestClient(app) as c:
        body = c.get("/api/skills").json()
    assert [s["name"] for s in body["skills"]] == ["alpha"]
    assert body["count"] == 1


def test_build_router_is_unattached(loader: SkillLoader) -> None:
    router = build_router(loader)
    assert router.prefix == "/api/skills"
    assert any(r.path == "/api/skills" for r in router.routes)


def test_routes_survive_an_asgi_mount(loader: SkillLoader) -> None:
    """Regression: the routes must resolve THROUGH a parent ``mount``.

    A deferred ``include_router`` placeholder is never expanded inside a mount,
    so ``/api/skills/*`` would 404 through the gateway while the bare app answers
    200. ``register`` extends the real route list instead.
    """
    child = FastAPI()
    register(child, loader)
    parent = FastAPI()
    parent.mount("/", child)
    with TestClient(parent) as c:
        assert c.get("/api/skills").status_code == 200
        assert c.get("/api/skills/alpha").status_code == 200
