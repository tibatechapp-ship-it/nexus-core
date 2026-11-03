"""Router — deterministic agent selection.

منذ v1.50.0 (ب3.1/ب3.4): سلسلة كسر التعادل ثلاثية معلنة —
**genome → درجة الأسطول الحية → الاسم**. درجة الأسطول تُقرأ من
``reports/fleet_inventory.json`` وقت التشغيل عبر ``src.fleet.reader``
(ف4 مغلقة: التوجيه يقرأ القياس)، والمكسور يُستبعد من الفوز. وكل قرار
توجيه عبر ``route_with_reason`` يسجّل ``{اسم، إطار، درجة وقت القرار}``
في سجل الأثر (``trace_event``).
"""

from __future__ import annotations
import re
from typing import Any, Optional, Set
from .aliases import expand
from .registry import AgentSpec, AgentRegistry, get_registry

_WORD = re.compile(r"[a-z][a-z0-9]+")


def _tokenize(text: str) -> Set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if len(w) >= 3}


def _score(spec: AgentSpec, tokens: Set[str]) -> float:
    scope_text = " ".join(spec.scope)
    domain_text = spec.domain.replace(".", " ")
    return float(len(tokens & _tokenize(scope_text)) * 2 + len(tokens & _tokenize(domain_text)))


def _fleet_rank(cands: list[str], registry: AgentRegistry) -> dict[tuple[str, str], Any]:
    """درجة الأسطول لكل مرشح — {(fw, name): FleetScore} للمتوفر منها فقط."""
    from src.fleet.reader import load_scores  # استيراد محلي: بلا دورة

    scores: dict[tuple[str, str], Any] = load_scores()
    if not scores:
        return {}
    keys: list[tuple[str, str]] = []
    for name in cands:
        spec = registry.spec(name) if hasattr(registry, "spec") else None
        fw = getattr(spec, "framework", "core") or "core"
        keys.append((fw, name))
    return {k: scores[k] for k in keys if k in scores}


def _break_ties(cands: list[str], registry: AgentRegistry, genome: Any) -> str:
    """سلسلة كسر التعادل: genome → درجة الأسطول الحية → الاسم."""
    if len(cands) <= 1:
        return cands[0] if cands else "coder"
    if genome is not None:

        def fit(n: str) -> float:
            try:
                return float(genome.fitness_of(n))
            except Exception:
                return 0.5

        best_fit = max(fit(n) for n in cands)
        top = [n for n in cands if fit(n) == best_fit]
        if len(top) == 1:
            return top[0]
        cands = top
    fleet = _fleet_rank(cands, registry)
    if fleet:
        from src.fleet.reader import pick_best

        best = pick_best(list(fleet.keys()), fleet)
        if best is not None:
            return best[1]
    return sorted(cands)[0]


def route(
    request: str,
    *,
    registry: Optional[AgentRegistry] = None,
    genome: Optional[Any] = None,
) -> str:
    if not request or not isinstance(request, str) or not request.strip():
        return "coder"
    reg = registry or get_registry()
    tokens = expand(_tokenize(request))
    scored = [(s.name, _score(s, tokens)) for s in reg.all()]
    best = max(s for _, s in scored)
    cands = [n for n, s in scored if s == best]
    return _break_ties(cands, reg, genome)


def route_with_reason(
    request: str,
    *,
    registry: Optional[AgentRegistry] = None,
    genome: Optional[Any] = None,
) -> dict:
    if not request or not isinstance(request, str) or not request.strip():
        return {"agent": "coder", "score": 0.0, "tokens": [], "alternatives": []}
    reg = registry or get_registry()
    raw_tokens = _tokenize(request)
    tokens = expand(raw_tokens)
    scored = [(s.name, _score(s, tokens)) for s in reg.all()]
    best = max(s for _, s in scored)
    chosen = route(request, registry=reg, genome=genome)
    result = {
        "agent": chosen,
        "score": best,
        "tokens": sorted(raw_tokens)[:10],
        "alternatives": [n for n, s in scored if s == best and n != chosen][:3],
    }
    # ب3.4: كل قرار توجيه يحمل درجته وقت القرار في سجل الأثر — best-effort
    try:
        from src.observability.trace import trace_event

        fleet = _fleet_rank([chosen], reg)
        info = fleet.get(("core", chosen)) or (next(iter(fleet.values())) if fleet else None)
        trace_event(
            agent=chosen,
            tool="route",
            outcome="ok",
            duration_ms=0.0,
            framework=(getattr(info, "framework", "core") if info else "core"),
            fleet_score=(float(getattr(info, "score", 0.0)) if info else 0.0),
            fleet_tier=(getattr(info, "tier", "C") if info else "C"),
        )
    except Exception:  # noqa: BLE001 — التتبع لا يُسقط التوجيه أبداً
        pass
    return result
