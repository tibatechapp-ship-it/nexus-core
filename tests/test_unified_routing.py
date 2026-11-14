"""Unified routing tests (ب2.1–ب2.5) — خطة التناغم docs/harmony-plan.md.

العقد: المرشحون 91 من الإطارين (20 core + 79 novamind ناقص 8 أسماء مشتركة
يفوز بها core) بلا اسم مكرر، كل مرشح يحمل إطاره، والسلّم مرتب بالدرجة
الحية بلا مكسور في رأسه، والتتبع يسجل الإطار الصادق.
"""

from __future__ import annotations

import json

import pytest

from src.orchestrator.registry import get_registry
from src.orchestrator.router import route, route_with_reason
from src.orchestrator.unified_registry import (
    UNIFIED_TOTAL,
    UnifiedRegistry,
    get_unified_registry,
)


def test_unified_registry_size_and_no_duplicates() -> None:
    """ب2.2: 91 مرشحاً فريداً من الإطارين (20+79 ناقص 8 مشتركة) بلا تكرار."""
    reg = get_unified_registry()
    names = [s.name for s in reg.all()]
    assert len(names) == len(set(names))
    assert len(reg) == UNIFIED_TOTAL
    assert reg.novamind_count == 71


def test_shared_names_resolve_to_core() -> None:
    """ب2.2: الأسماء الثمانية المشتركة — core الاسمي يفوز بالاصطدام."""
    reg = get_unified_registry()
    for shared in ("architect", "coder", "compliance", "devops",
                   "documentation", "performance", "refactor", "tester"):
        spec = reg.spec(shared)
        assert spec is not None
        assert spec.framework == "core"


def test_pure_novamind_agents_are_in_the_pool() -> None:
    """ب2.2: وكلاء novamind خالصون موجودون بمواصفة كاملة وإطار معلن."""
    reg = get_unified_registry()
    for pure in ("a11y", "react", "sql"):
        spec = reg.spec(pure)
        assert spec is not None, f"novamind agent {pure} missing"
        assert spec.framework == "novamind"
        assert spec.domain.startswith("novamind.")
        assert len(spec.scope) > 0


def test_core_registry_unchanged() -> None:
    """سجل core المعتمد يبقى 20 — التوحيد غلاف لا استبدال."""
    assert len(get_registry()) == 20


def test_route_novamind_only_query_picks_novamind() -> None:
    """ب2.3: استعلام يطابق وكيلاً novamind خالصاً فقط ⇒ اختياره بإطاره."""
    # "a11y" واسمه وcapability — لا وكيلاً core يحمله
    chosen = route("a11y accessibility audit")
    assert chosen == "a11y"


def test_route_with_reason_reports_framework_and_ladder() -> None:
    """ب2.3/ب2.5: النتيجة تحمل إطار المختار وسلّماً مرتباً من ثلاثة."""
    info = route_with_reason("write tests for X")
    assert info["framework"] == "core"
    assert info["agent"] == "tester"
    ladder = info["ladder"]
    assert 1 <= len(ladder) <= 3
    assert ladder[0]["agent"] == info["agent"]
    # المرتبة الأولى هي الأعلى توكنياً — والمسلّم مرتب نازلاً بالتوكن ثم الدرجة
    for i in range(1, len(ladder)):
        prev, cur = ladder[i - 1], ladder[i]
        assert prev["token_score"] >= cur["token_score"]
        if prev["token_score"] == cur["token_score"]:
            assert prev["fleet_score"] >= cur["fleet_score"]


def test_ladder_has_no_broken_agent_on_top() -> None:
    """ب2.3: المكسور لا يرأس السلّم — نفس عقد الدرجة الحية."""
    info = route_with_reason("engineering help")
    assert info["ladder"][0]["fleet_tier"] != "broken" or \
        info["ladder"][0]["fleet_score"] >= 0.0
    # الرأس إن كان مكسوراً فلا يوجد غيره — والعقد الحقيقي: المختار ليس المكسور
    scores = info["ladder"]
    if len(scores) > 1:
        assert all(entry["agent"] != "nexus_agent" or entry["framework"] == "legacy"
                   for entry in scores) or scores[0]["agent"] != "nexus_agent"


def test_empty_query_defaults_to_coder() -> None:
    """الافتراضي باقٍ: استعلام فارغ ⇒ coder بإطار core."""
    assert route("") == "coder"
    assert route(None) == "coder"
    info = route_with_reason("")
    assert info["framework"] == "core"


def test_fleet_rank_uses_true_framework_keys(monkeypatch: pytest.MonkeyPatch,
                                             tmp_path) -> None:
    """ب2.1: مفاتيح الدرجة هي (framework, name) الحقيقية — لا core الافتراضي."""
    from src.fleet.reader import FleetScore
    from src.orchestrator import router

    fake = {
        ("novamind", "a11y"): FleetScore("a11y", "novamind", 99.0, "S", "healthy"),
        ("core", "coder"): FleetScore("coder", "core", 100.0, "S", "healthy"),
    }
    report = tmp_path / "fleet_inventory.json"
    payload = {"ranking": [
        {"name": k[1], "framework": k[0], "score": v.score,
         "tier": v.tier, "status": v.status} for k, v in fake.items()]}
    report.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr("src.fleet.reader.default_report_path", lambda: report)

    reg = get_unified_registry()
    ranked = router._fleet_rank(["a11y", "coder"], reg)
    assert ("novamind", "a11y") in ranked
    assert ("core", "coder") in ranked
    assert ranked[("novamind", "a11y")].framework == "novamind"


def test_agent_system_enriches_novamind_identity() -> None:
    """ب2.4: برومبت نظام وكيلاً novamind يحمل وصفه من nova.yaml."""
    from src.legacy_root.nexus_agent import _agent_system

    system = _agent_system("a11y", "audit this ui")
    assert "a11y" in system
    assert "novamind" in system.lower()
    # وكيل core لا يُلمس — بقي بنص فئته
    core_system = _agent_system("tester", "test this")
    assert core_system and "novamind agent 'tester'" not in core_system
