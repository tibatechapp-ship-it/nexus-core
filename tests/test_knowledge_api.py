"""Tests for ``src.knowledge.api`` — the ``/api/knowledge/*`` HTTP surface.

Skipped cleanly when FastAPI is absent (the phone gate stays green). The routes
are registered by hand (``register``), NOT via a deferred ``include_router``, so
one test drives them through a real ASGI ``mount`` — the same shape the unified
gateway uses. A bare-app test cannot catch a deferred-router regression.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.knowledge.api import build_router, register  # noqa: E402
from src.knowledge.base import KnowledgeBase  # noqa: E402


#────────────────────────────── helpers ──────────────────────────────#


def _write(directory: Path, name: str, text: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.md").write_text(text, encoding="utf-8")


@pytest.fixture()
def kb(tmp_path: Path) -> KnowledgeBase:
    seed = tmp_path / "seed"
    _write(seed, "nexus-core", "---\ntitle: Nexus\ncategory: core\n---\nbody\n")
    _write(seed, "notes", "---\ntitle: Notes\ncategory: misc\n---\nscratch\n")
    return KnowledgeBase(seed, tmp_path / "user")


@pytest.fixture()
def client(kb: KnowledgeBase) -> Iterator[TestClient]:
    app = FastAPI()
    register(app, kb)
    with TestClient(app) as c:
        yield c


#────────────────────────────── list ──────────────────────────────#


def test_list_returns_count_and_docs(client: TestClient) -> None:
    """The list route reports a count, stats and content-free doc rows."""
    body = client.get("/api/knowledge").json()
    assert body["count"] == 2
    assert {d["name"] for d in body["docs"]} == {"nexus-core", "notes"}
    assert "content" not in body["docs"][0]
    assert body["stats"]["docs"] == 2


def test_doc_returns_full_content(client: TestClient) -> None:
    """A single doc carries its content."""
    body = client.get("/api/knowledge/notes").json()
    assert body["name"] == "notes"
    assert body["content"] == "scratch"


def test_missing_doc_is_404(client: TestClient) -> None:
    """An unknown doc name is a clean 404, not a crash."""
    assert client.get("/api/knowledge/nope").status_code == 404


#────────────────────────────── router wiring ──────────────────────────────#


def test_build_router_is_not_yet_attached(kb: KnowledgeBase) -> None:
    """``build_router`` returns an unattached router (mountable by callers)."""
    router = build_router(kb)
    assert router.prefix == "/api/knowledge"
    assert any(r.path == "/api/knowledge" for r in router.routes)


def test_routes_survive_an_asgi_mount(kb: KnowledgeBase) -> None:
    """Regression: the routes must resolve THROUGH a parent ``mount``.

    ``app.include_router`` is deferred in recent FastAPI — a sub-app reached via
    ``parent.mount("/", app)`` never expands the placeholder, so the routes 404
    through the gateway while the bare app answers 200. ``register`` extends the
    real route list instead, so this must stay green.
    """
    child = FastAPI()
    register(child, kb)
    parent = FastAPI()
    parent.mount("/", child)
    with TestClient(parent) as c:
        assert c.get("/api/knowledge").status_code == 200
        assert c.get("/api/knowledge/notes").status_code == 200
