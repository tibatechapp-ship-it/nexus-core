"""اختبارات التوجيه العرقي بالدرجة (ب3.1/ب3.2/ب3.4 — v1.50.0).

* **ب3.1**: قارئ لوحة الترتيب الحي — بمصفوفة درجات اصطناعية: الأعلى
  يفوز دائماً، والمكسور يُستبعد من الفوز حتى لو كانت درجته الأعلى.
* **ب3.4**: كل قرار توجيه يسجّل ``{اسم، إطار، درجة وقت القرار}`` في
  سجل الأثر — الاختبار يقرأ السجل ويجد الحقول لقرارين مختلفين.
* **ب3.2**: بوابة ترقية الطبقة عبر evalsuite — الرفض بلا نجاح فعلي
  هو العقد، وسجل الترقية يحمل ``eval_suite``.
"""

from __future__ import annotations

from src.fleet.reader import FleetScore, load_scores, pick_best, rank_candidates
from src.observability.trace import read_recent


def _scores() -> dict[tuple[str, str], FleetScore]:
    return {
        ("core", "alpha"): FleetScore("alpha", "core", 100.0, "S", "healthy"),
        ("core", "beta"): FleetScore("beta", "core", 92.0, "A", "healthy"),
        ("core", "gamma"): FleetScore("gamma", "core", 70.0, "B", "healthy"),
        ("core", "delta"): FleetScore("delta", "core", 99.0, "S", "broken"),
        ("novamind", "epsilon"): FleetScore("epsilon", "novamind", 60.0, "C", "healthy"),
    }


def test_highest_score_wins_always() -> None:
    """ب3.1: الأعلى درجة يفوز دائماً — بغضّ الإطار والترتيب الوارد."""
    ranked = rank_candidates(
        [("core", "gamma"), ("core", "alpha"), ("core", "beta"), ("novamind", "epsilon")],
        _scores(),
    )
    assert ranked[0] == ("core", "alpha")
    assert ranked[1] == ("core", "beta")
    assert ranked[2] == ("core", "gamma")
    assert ranked[3] == ("novamind", "epsilon")
    assert pick_best([("core", "beta"), ("core", "alpha")], _scores()) == (
        "core",
        "alpha",
    )


def test_broken_agent_is_excluded_from_winning() -> None:
    """ب3.1: المكسور يُستبعد حتى لو كانت درجته الأعلى — لا فوز زوراً."""
    ranked = rank_candidates([("core", "delta"), ("core", "alpha"), ("core", "beta")], _scores())
    assert ranked[0] == ("core", "alpha")  # delta (99.0) مكسور → ذيل لا رأس
    assert ranked[-1] == ("core", "delta")
    assert pick_best([("core", "delta")], _scores()) is None  # كلهم مكسورون


def test_unmeasured_candidate_loses_to_measured() -> None:
    """بلا قياس لا مجاملة: غير المقيس أدنى من أي مقيس عند النظر."""
    sparse = {("core", "alpha"): FleetScore("alpha", "core", 85.0, "A", "healthy")}
    ranked = rank_candidates([("core", "ghost"), ("core", "alpha")], sparse)
    assert ranked[0] == ("core", "alpha")
    assert ranked[1] == ("core", "ghost")


def test_empty_or_missing_report_is_declared_empty() -> None:
    """غياب التقرير = {} معلن — لا انفجار ولا درجات مخترعة."""
    from pathlib import Path

    assert load_scores(Path("/no/such/fleet_inventory.json")) == {}


def test_route_with_reason_traces_fleet_fields(tmp_path, monkeypatch) -> None:
    """ب3.4: القراران المختلفان يحملان {اسم، إطار، درجة} في سجل الأثر."""
    from src.orchestrator.router import route_with_reason

    monkeypatch.setenv("NEXUS_TRACE_PATH", str(tmp_path / "trace.jsonl"))
    first = route_with_reason("write unit tests for the parser module")
    second = route_with_reason("review the security of the auth flow")
    assert first["agent"] and second["agent"]

    events = [e for e in read_recent(limit=20) if e.get("tool") == "route"]
    assert len(events) >= 2
    # read_recent تصاعدية زمنياً — نقارن بالمجموعة لا بالترتيب
    traced = {e["agent"]: e for e in events}
    assert {first["agent"], second["agent"]} <= set(traced)
    for agent in (first["agent"], second["agent"]):
        event = traced[agent]
        assert "framework" in event and "fleet_score" in event
        assert "fleet_tier" in event
        assert isinstance(event["fleet_score"], (int, float))


def test_promotion_gate_refuses_without_eval_success(tmp_path, monkeypatch) -> None:
    """ب3.2: لا ترقية إلى S بلا eval_suite=passed — الرفض معلن بسبب."""
    from src.fleet import promotion

    monkeypatch.setattr(promotion, "PROMOTION_LOG", tmp_path / "promotion_log.json")
    refused = promotion.promotion_gate(
        framework="novamind",
        name="a11y",
        current_tier="A",
        target_tier="S",
        eval_suite="failed",
    )
    assert refused["allowed"] is False and "refused" in refused["reason"]
    assert refused["eval_suite"] == "failed"
    unmeasured = promotion.promotion_gate(
        framework="novamind",
        name="a11y",
        current_tier="A",
        target_tier="S",
    )
    assert unmeasured["allowed"] is False
    assert unmeasured["eval_suite"] == "unmeasured"


def test_promotion_gate_allows_with_eval_success_and_logs(tmp_path, monkeypatch) -> None:
    """ب3.2: النجاح الفعلي يفتح البوابة، والسجل يحمل eval_suite."""
    from src.fleet import promotion

    monkeypatch.setattr(promotion, "PROMOTION_LOG", tmp_path / "promotion_log.json")

    def fake_runner(framework: str, name: str, category: str) -> dict:
        return {"eval_suite": "passed", "passed": 1, "total": 1, "reason": "ok"}

    gate = promotion.eval_gate("novamind", "a11y", category="ui", runner=fake_runner)
    assert gate["eval_suite"] == "passed"
    allowed = promotion.promotion_gate(
        framework="novamind",
        name="a11y",
        current_tier="A",
        target_tier="S",
        eval_suite=gate["eval_suite"],
    )
    assert allowed["allowed"] is True
    log = promotion.append_log(allowed, path=tmp_path / "promotion_log.json")
    assert log[-1]["eval_suite"] == "passed"
    assert log[-1]["agent"] == "a11y"
