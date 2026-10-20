"""Orchestrator — plan + decompose + execute + jury gate."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from .decomposer import SubTask, decompose, merge_outputs
from .risk import RiskLevel, classify, explain
from .router import route, route_with_reason
from .registry import get_registry

_TRUE = ("1", "true", "yes", "on")


def decompose_enabled() -> bool:
    """Feature flag: decomposition is ON unless ``NEXUS_DECOMPOSE`` is falsey.

    Set ``NEXUS_DECOMPOSE=0`` (or ``off``/``no``/``false``) to fall back to the
    single-agent execute path, byte-for-byte the pre-v1.24.0 behaviour.
    """
    return os.environ.get("NEXUS_DECOMPOSE", "1").strip().lower() in _TRUE


@dataclass
class Plan:
    request: str
    agent: str
    risk: RiskLevel
    risk_reason: str
    router_reason: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)


class Orchestrator:
    def __init__(
        self,
        *,
        genome: Optional[Any] = None,
        jury_members: Optional[List[str]] = None,
        llm: Optional[Any] = None,
    ) -> None:
        self.genome = genome
        self.jury_members = list(jury_members or [])
        self.llm = llm
        self.registry = get_registry()

    def plan(self, request: str) -> Plan:
        risk = classify(request)
        agent = route(request, registry=self.registry, genome=self.genome)
        return Plan(
            request=request, agent=agent, risk=risk,
            risk_reason=explain(request)["reason"],
            router_reason=route_with_reason(
                request, registry=self.registry, genome=self.genome))

    def decompose(self, request: str) -> List[SubTask]:
        """Split ``request`` into per-agent subtasks (see :mod:`.decomposer`)."""
        return decompose(request, registry=self.registry, genome=self.genome)

    def execute(
        self,
        request: str,
        *,
        runner: Optional[Callable[[str, str], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        if runner is None:
            return {"plan": self.plan(request).__dict__, "jury": None,
                    "output": None, "ok": None}
        if decompose_enabled():
            subtasks = self.decompose(request)
            if len(subtasks) > 1:
                return self._execute_many(request, subtasks, runner)
        return self._execute_one(request, runner)

    # ── single-agent path (the pre-v1.24.0 behaviour) ──────────────────────
    def _execute_one(
        self,
        request: str,
        runner: Callable[[str, str], Dict[str, Any]],
    ) -> Dict[str, Any]:
        p = self.plan(request)
        result: Dict[str, Any] = {"plan": p.__dict__, "jury": None,
                                   "output": None, "ok": None}
        try:
            out = runner(p.agent, request) or {}
            result["output"] = out.get("output")
            result["ok"] = bool(out.get("ok", True))
        except Exception as e:
            result["error"] = str(e)[:200]
            result["ok"] = False
            return result
        self._apply_jury(result, p.risk)
        return result

    # ── decomposed path: run every subtask, merge, judge the block ONCE ────
    def _execute_many(
        self,
        request: str,
        subtasks: List[SubTask],
        runner: Callable[[str, str], Dict[str, Any]],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "plan": self.plan(request).__dict__,
            "decomposed": True,
            "subtasks": [s.to_dict() for s in subtasks],
            "results": [],
            "jury": None,
            "output": None,
            "ok": True,
        }
        outputs: List[dict] = []
        for sub in subtasks:
            try:
                out = runner(sub.agent, sub.request) or {}
            except Exception as e:
                out = {"output": None, "ok": False, "error": str(e)[:200]}
            outputs.append(out)
            row = {
                "agent": sub.agent, "risk": sub.risk.value,
                "output": out.get("output"),
                "ok": bool(out.get("ok", True)),
            }
            if out.get("error"):
                row["error"] = out["error"]
            result["results"].append(row)
            if not out.get("ok", True):
                result["ok"] = False
        result["output"] = merge_outputs(subtasks, outputs)
        # One jury decision over the merged block, at the HIGHEST subtask risk.
        top_risk = max((s.risk for s in subtasks), default=RiskLevel.LOW)
        self._apply_jury(result, top_risk)
        return result

    def _apply_jury(self, result: Dict[str, Any], risk: RiskLevel) -> None:
        """Run the jury on ``result["output"]`` when ``risk`` is HIGH."""
        if risk != RiskLevel.HIGH or not self.jury_members:
            return
        from src.novamind.council.jury import judge
        v = judge(str(result["output"] or ""), risk=risk,
                  members=self.jury_members, llm=self.llm)
        result["jury"] = v.__dict__ if v else None
        if v and not v.approved:
            result["ok"] = False
