"""Router — deterministic agent selection over the unified fleet.

منذ v1.50.0 (ب3.1/ب3.4): سلسلة كسر التعادل ثلاثية معلنة —
**genome → درجة الأسطول الحية → الاسم**. درجة الأسطول تُقرأ من
``reports/fleet_inventory.json`` وقت التشغيل عبر ``src.fleet.reader``
(ف4 مغلقة: التوجيه يقرأ القياس)، والمكسور يُستبعد من الفوز. وكل قرار
توجيه عبر ``route_with_reason`` يسجّل ``{اسم، إطار، درجة وقت القرار}``
في سجل الأثر (``trace_event``).

منذ v1.61.0 (خطة التناغم ب2.2/ب2.3 — ``docs/harmony-plan.md``):
المرشحون من **السجل الموحد** (``src.orchestrator.unified_registry``) —
20 core + 79 novamind لا 20 من 106 — وكل مرشح يحمل إطاره (`framework`)
فتصير مفاتيح لوحة الأسطول ``{(framework, name)}`` صحيحة (ب2.1)،
والنتيجة تكسب ``ladder``: أفضل ثلاثة مرشحين مرتبين (الدرجة التوكنية
ثم الدرجة الحية ثم الاسم) — سلّم التصعيد الجاهز للمُنفّذ.

وامتداداً لقاعدة «core الاسمي يفوز بالاصطدام» (ب2.2): عند تنافس
الإطارين على أعلى درجة يفوز مرشح core بفارق نصف إصابة مجال
(``CORE_PRECEDENCE_BONUS = 1.5`` على إصابة مجال = 2.0) — قاعدة معلنة
تحفظ عقود الأمان القائمة (أفعال الأمان/التدمير تهبط للمدقّق core) بلا
سلب وكيل novamind أحقّ منه بنقطتين أو أكثر.
"""

from __future__ import annotations
import re
from typing import Any, List, Optional, Protocol, Set
from .aliases import expand
from .registry import AgentSpec, AgentRegistry, get_registry

_WORD = re.compile(r"[a-z][a-z0-9]+")


class _RoutingRegistry(Protocol):
    """أدنى عقد سجل يحتاجه التوجيه — يحققه السجلان core والموحد بنيوياً."""

    def spec(self, name: str) -> Optional[AgentSpec]: ...

    def all(self) -> List[AgentSpec]: ...

#: جائزة الأولوية الأساسية (ب2.2): نصف إصابة مجال — انظر رأس الوحدة.
CORE_PRECEDENCE_BONUS: float = 1.5


def _tokenize(text: str) -> Set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if len(w) >= 3}


def _score(spec: AgentSpec, tokens: Set[str]) -> float:
    scope_text = " ".join(spec.scope)
    domain_text = spec.domain.replace(".", " ")
    score = float(len(tokens & _tokenize(scope_text)) * 2 + len(tokens & _tokenize(domain_text)))
    if str(getattr(spec, "framework", "core") or "core") == "core":
        score += CORE_PRECEDENCE_BONUS
    return score


def _default_registry() -> _RoutingRegistry:
    """السجل الموحد افتراضياً (ب2.2) — والسجل الأصغر core احتياطاً معلناً."""
    try:
        from .unified_registry import get_unified_registry

        return get_unified_registry()
    except Exception:  # noqa: BLE001 — فساد nova.yaml لا يوقف التوجيه
        return get_registry()


def _framework_of(registry: Any, name: str) -> str:
    spec = registry.spec(name) if hasattr(registry, "spec") else None
    return str(getattr(spec, "framework", "core") or "core")


def _fleet_rank(cands: list[str], registry: Any) -> dict[tuple[str, str], Any]:
    """درجة الأسطول لكل مرشح — {(fw, name): FleetScore} للمتوفر منها فقط.

    ب2.1: الإطار يُقرأ من واصفة المرشح الحقيقية لا افتراضياً.
    """
    from src.fleet.reader import load_scores  # استيراد محلي: بلا دورة

    scores: dict[tuple[str, str], Any] = load_scores()
    if not scores:
        return {}
    keys: list[tuple[str, str]] = []
    for name in cands:
        spec = registry.spec(name) if hasattr(registry, "spec") else None
        fw = str(getattr(spec, "framework", "core") or "core")
        keys.append((fw, name))
    return {k: scores[k] for k in keys if k in scores}


def _break_ties(cands: list[str], registry: _RoutingRegistry, genome: Any) -> str:
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


def _ladder(scored: list[tuple[str, float]], registry: Any,
            k: int = 3) -> list[dict[str, Any]]:
    """سلّم التصعيد (ب2.3): أفضل k مرشحين — التوكن ثم الدرجة الحية ثم الاسم."""
    from src.fleet.reader import load_scores, rank_candidates

    keys: list[tuple[tuple[str, str], float]] = []
    for name, ts in scored:
        keys.append(((_framework_of(registry, name), name), ts))
    scores = load_scores()
    position = {key: i for i, key in enumerate(
        rank_candidates([key for key, _ in keys], scores))}
    ordered = sorted(keys,
                     key=lambda kt: (-kt[1], position.get(kt[0], len(keys)), kt[0][1]))
    ladder: list[dict[str, Any]] = []
    for (fw, name), ts in ordered[:k]:
        info = scores.get((fw, name))
        ladder.append({
            "agent": name,
            "framework": fw,
            "token_score": ts,
            "fleet_score": float(getattr(info, "score", 0.0)) if info else 0.0,
            "fleet_tier": str(getattr(info, "tier", "C")) if info else "C",
        })
    return ladder


def route(
    request: str,
    *,
    registry: Optional[_RoutingRegistry] = None,
    genome: Optional[Any] = None,
) -> str:
    if not request or not isinstance(request, str) or not request.strip():
        return "coder"
    reg = registry or _default_registry()
    tokens = expand(_tokenize(request))
    scored = [(s.name, _score(s, tokens)) for s in reg.all()]
    best = max(s for _, s in scored)
    cands = [n for n, s in scored if s == best]
    return _break_ties(cands, reg, genome)


def route_with_reason(
    request: str,
    *,
    registry: Optional[_RoutingRegistry] = None,
    genome: Optional[Any] = None,
) -> dict:
    if not request or not isinstance(request, str) or not request.strip():
        return {"agent": "coder", "score": 0.0, "tokens": [], "alternatives": [],
                "framework": "core", "ladder": []}
    reg = registry or _default_registry()
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
        "framework": _framework_of(reg, chosen),
        "ladder": _ladder(scored, reg),
    }
    # ب3.4: كل قرار توجيه يحمل درجته وقت القرار في سجل الأثر — best-effort
    try:
        from src.observability.trace import trace_event

        fw = str(result.get("framework", "core"))
        fleet = _fleet_rank([chosen], reg)
        info = fleet.get((fw, chosen)) or (next(iter(fleet.values())) if fleet else None)
        trace_event(
            agent=chosen,
            tool="route",
            outcome="ok",
            duration_ms=0.0,
            framework=fw,
            fleet_score=(float(getattr(info, "score", 0.0)) if info else 0.0),
            fleet_tier=(str(getattr(info, "tier", "C")) if info else "C"),
        )
    except Exception:  # noqa: BLE001 — التتبع لا يُسقط التوجيه أبداً
        pass
    return result
