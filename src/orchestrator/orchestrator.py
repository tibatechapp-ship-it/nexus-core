"""Orchestrator — plan + execute + jury gate."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional
from .risk import RiskLevel, classify, explain
from .router import route, route_with_reason
from .registry import get_registry


@dataclass
class Plan:
    request: str
    agent: str
    risk: RiskLevel
    risk_reason: str
    router_reason: dict
    metadata: dict = field(default_factory=dict)


class Orchestrator:
    def __init__(self, *, genome=None, jury_members=None, llm=None):
        self.genome = genome
        self.jury_members = list(jury_members or [])
        self.llm = llm
        self.registry = get_registry()

    def plan(self, request):
        risk = classify(request)
        agent = route(request, registry=self.registry, genome=self.genome)
        return Plan(request=request, agent=agent, risk=risk,
                    risk_reason=explain(request)["reason"],
                    router_reason=route_with_reason(
                        request, registry=self.registry, genome=self.genome))

    def execute(self, request, *, runner=None):
        p = self.plan(request)
        result = {"plan": p.__dict__, "jury": None,
                  "output": None, "ok": None}
        if runner is None:
            return result
        try:
            out = runner(p.agent, request) or {}
            result["output"] = out.get("output")
            result["ok"] = bool(out.get("ok", True))
        except Exception as e:
            result["error"] = str(e)[:200]
            result["ok"] = False
            return result
        if p.risk == RiskLevel.HIGH and self.jury_members:
            from src.novamind.council.jury import judge
            v = judge(str(result["output"] or ""), risk=p.risk,
                      members=self.jury_members, llm=self.llm)
            result["jury"] = v.__dict__ if v else None
            if v and not v.approved:
                result["ok"] = False
        return result
