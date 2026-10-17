"""HTTP surface for the training pipeline (``/api/training/*``).

Mounted by the unified gateway.  Kept in its own module so the pure engine can
be imported (and tested) without FastAPI installed.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .engine import TrainingEngine, get_engine
from .models import GRADUATION_MIN_SCORE
from .store import get_store


class TrainRequest(BaseModel):
    """Body of ``POST /api/training/run``."""

    agent_id: str = Field(..., min_length=1, max_length=128)
    spec: Optional[str] = Field(default=None, max_length=64)
    quality: float = Field(default=0.85, ge=0.0, le=1.0)
    salt: str = Field(default="", max_length=64)


class BatchTrainRequest(BaseModel):
    """Body of ``POST /api/training/batch``."""

    agent_ids: List[str] = Field(default_factory=list, max_length=200)
    spec: Optional[str] = Field(default=None, max_length=64)
    quality: float = Field(default=0.85, ge=0.0, le=1.0)
    salt: str = Field(default="", max_length=64)


def register(app: Any, engine: Optional[TrainingEngine] = None) -> APIRouter:
    """Register the training routes on ``app``.

    ``app.include_router`` is *deferred* in recent FastAPI releases: the routes
    are kept inside an ``_IncludedRouter`` placeholder and expanded lazily.  A
    sub-application that is ``mount``-ed under a parent never goes through that
    expansion, so ``/api/training/*`` 404s inside the unified gateway even
    though it works on a bare app.  Adding the concrete routes directly avoids
    the placeholder entirely.
    """
    router = build_router(engine)
    app.router.routes.extend(router.routes)
    return router


def build_router(engine: Optional[TrainingEngine] = None) -> APIRouter:
    """Build the training router (``engine`` injectable for tests)."""
    router = APIRouter(prefix="/api/training", tags=["training"])
    eng = engine or get_engine()

    @router.get("/status")
    async def training_status() -> Dict[str, Any]:
        """Aggregate counters for the dashboard."""
        store = eng.store
        stats = store.stats()
        stats["min_score"] = GRADUATION_MIN_SCORE
        stats["certified_agents"] = len({
            c["agent_id"] for c in store.list_certificates(limit=500)
        })
        stats["field"] = eng.field_stats()
        return stats

    @router.get("/agents")
    async def training_agents(limit: int = 100) -> Dict[str, Any]:
        """Every agent that has ever trained, with its latest run."""
        bounded = max(1, min(int(limit), 500))
        runs = eng.store.list_runs(limit=bounded)
        seen: Dict[str, Dict[str, Any]] = {}
        for run in runs:
            if run.agent_id not in seen:
                seen[run.agent_id] = {
                    "agent_id": run.agent_id,
                    "spec": run.spec,
                    "latest_run": run.to_dict(),
                }
        certs = eng.store.list_certificates(limit=500)
        for cert in certs:
            row = seen.get(cert["agent_id"])
            if row is not None:
                row["certificate_id"] = cert["certificate_id"]
        return {"count": len(seen), "agents": list(seen.values())}

    @router.get("/plan/{agent_id}")
    async def training_plan(agent_id: str, spec: Optional[str] = None) -> Dict[str, Any]:
        """The plan an agent would run, plus its last result."""
        return eng.plan(agent_id, spec)

    @router.post("/run")
    async def training_run(req: TrainRequest) -> Dict[str, Any]:
        """Train one agent and return the recorded run."""
        run = eng.train(
            req.agent_id, req.spec, quality=req.quality, salt=req.salt
        )
        return run.to_dict()

    @router.post("/batch")
    async def training_batch(req: BatchTrainRequest) -> Dict[str, Any]:
        """Train several agents in one call."""
        if not req.agent_ids:
            raise HTTPException(status_code=400, detail="agent_ids is empty")
        runs = eng.train_batch(
            req.agent_ids, req.spec, quality=req.quality, salt=req.salt
        )
        return {
            "count": len(runs),
            "graduated": sum(1 for r in runs if r.certified),
            "runs": [r.to_dict() for r in runs],
        }

    @router.get("/runs")
    async def training_runs(
        agent_id: Optional[str] = None, limit: int = 50
    ) -> Dict[str, Any]:
        """Run history, newest first."""
        runs = eng.store.list_runs(agent_id=agent_id, limit=limit)
        return {"count": len(runs), "runs": [r.to_dict() for r in runs]}

    @router.get("/runs/{run_id}")
    async def training_run_detail(run_id: str) -> Dict[str, Any]:
        """One run by id."""
        run = eng.store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run.to_dict()

    @router.get("/certificates")
    async def training_certificates(
        agent_id: Optional[str] = None, limit: int = 50
    ) -> Dict[str, Any]:
        """Issued certificates, newest first."""
        certs = eng.store.list_certificates(agent_id=agent_id, limit=limit)
        return {"count": len(certs), "certificates": certs}

    @router.get("/field")
    async def training_field() -> Dict[str, Any]:
        """Field-loop counters (lessons absorbed, genome feeds, evolutions)."""
        return eng.field_stats()

    @router.get("/lessons")
    async def training_lessons(
        agent_id: Optional[str] = None, limit: int = 50
    ) -> Dict[str, Any]:
        """Lessons the field loop absorbed, most confident first."""
        items = eng.lessons(agent_id, limit=limit)
        return {
            "count": len(items),
            "lessons": [item.to_dict() for item in items],
        }

    @router.get("/fitness")
    async def training_fitness(limit: int = 50) -> Dict[str, Any]:
        """Per-agent genome standings (fitness, evidence, next action)."""
        items = eng.fitness(limit=limit)
        return {"count": len(items), "agents": items}

    @router.post("/evolve")
    async def training_evolve() -> Dict[str, Any]:
        """Run an evolution pass now and report what it changed."""
        actions = eng.evolve()
        return {
            "count": len(actions),
            "mutated": [a["agent_id"] for a in actions if a["mutated"]],
            "actions": actions,
        }

    return router


def router_for_app(app: Any) -> APIRouter:
    """Build a router bound to ``app``'s process-wide training store."""
    return build_router(get_engine(store=get_store()))


__all__ = ["build_router", "register", "TrainRequest", "BatchTrainRequest"]
