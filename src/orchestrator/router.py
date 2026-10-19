"""Router — deterministic agent selection."""
from __future__ import annotations
import re
from typing import Any, Optional, Set
from .registry import AgentSpec, AgentRegistry, get_registry

_WORD = re.compile(r"[a-z][a-z0-9]+")


def _tokenize(text: str) -> Set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if len(w) >= 3}


def _score(spec: AgentSpec, tokens: Set[str]) -> float:
    scope_text = " ".join(spec.scope)
    domain_text = spec.domain.replace(".", " ")
    return float(len(tokens & _tokenize(scope_text)) * 2
                 + len(tokens & _tokenize(domain_text)))


def route(
    request: str,
    *,
    registry: Optional[AgentRegistry] = None,
    genome: Optional[Any] = None,
) -> str:
    if not request or not isinstance(request, str) or not request.strip():
        return "coder"
    reg = registry or get_registry()
    tokens = _tokenize(request)
    scored = [(s.name, _score(s, tokens)) for s in reg.all()]
    best = max(s for _, s in scored)
    cands = [n for n, s in scored if s == best]
    if len(cands) > 1 and genome is not None:
        def fit(n: str) -> float:
            try:
                return float(genome.fitness_of(n))
            except Exception:
                return 0.5
        cands = sorted(cands, key=lambda n: (-fit(n), n))
    return cands[0] if cands else "coder"


def route_with_reason(
    request: str,
    *,
    registry: Optional[AgentRegistry] = None,
    genome: Optional[Any] = None,
) -> dict:
    if not request or not isinstance(request, str) or not request.strip():
        return {"agent": "coder", "score": 0.0, "tokens": [], "alternatives": []}
    reg = registry or get_registry()
    tokens = _tokenize(request)
    scored = [(s.name, _score(s, tokens)) for s in reg.all()]
    best = max(s for _, s in scored)
    chosen = route(request, registry=reg, genome=genome)
    return {"agent": chosen, "score": best, "tokens": sorted(tokens)[:10],
            "alternatives": [n for n, s in scored if s == best and n != chosen][:3]}
