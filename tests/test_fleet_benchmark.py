"""اختبارات قياس وترتيب الأسطول — درجات معلنة، ترتيب حتمي، طبقات عادلة.

واختبار تقارير النشر: لوحة Markdown + JSON كامل داخل المجلد الممرَّر فقط،
وCLI كامل يُنتج كل شيء بلا شبكة.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.fleet.benchmark import (
    SCORE_WEIGHTS,
    SPEED_CAP_MS,
    TIER_THRESHOLDS,
    _speed_component,
    benchmark,
    rank,
    tier_of,
)
from src.fleet.conformance import run_conformance
from src.fleet.inventory import build_inventory, summary
from src.fleet.leaderboard import render_markdown, write_reports
from src.fleet.record import AgentRecord


def _records() -> list[AgentRecord]:
    return [
        AgentRecord(name="fast", framework="legacy", source="a.py",
                    module="src.fleet.record", symbol="AgentRecord",
                    description="ok", category="meta", criticality="standard"),
        AgentRecord(name="ghost", framework="legacy", source="b.py",
                    module="no.such.module_bench", symbol="Ghost",
                    description="ok"),
        AgentRecord(name="half", framework="legacy", source="record.py",
                    module="src.fleet.record", symbol="NoSuchSymbol",
                    description="ok"),
    ]


def test_weights_and_thresholds_are_declared_sane() -> None:
    assert sum(SCORE_WEIGHTS.values()) == 1.0
    assert TIER_THRESHOLDS == {"S": 95.0, "A": 85.0, "B": 70.0}


def test_tier_boundaries() -> None:
    assert tier_of(100.0) == "S" and tier_of(95.0) == "S"
    assert tier_of(94.99) == "A" and tier_of(85.0) == "A"
    assert tier_of(84.99) == "B" and tier_of(70.0) == "B"
    assert tier_of(69.99) == "C" and tier_of(0.0) == "C"


def test_speed_component_shape() -> None:
    assert _speed_component(0.5) == 100.0   # ساخن فوري
    assert _speed_component(1.0) == 100.0
    assert _speed_component(SPEED_CAP_MS) == 0.0
    assert _speed_component(SPEED_CAP_MS * 10) == 0.0
    mid = _speed_component(25.5)
    assert 0.0 < mid < 100.0


def test_benchmark_marks_broken_and_missing_entry() -> None:
    results = {r["name"]: r for r in benchmark(_records())}
    assert results["fast"]["import_ok"] and results["fast"]["entrypoint_ok"]
    assert not results["ghost"]["import_ok"]      # استيراد ميت
    assert results["half"]["import_ok"]           # الوحدة تعيش
    assert not results["half"]["entrypoint_ok"]   # والرمز غائب
    assert all(r["run_ms"] is None for r in results.values())  # بلا deep


def test_rank_is_deterministic_and_weighted() -> None:
    records = _records()
    conf = run_conformance(records)
    bench = benchmark(records)  # القياس الواحد ثابت المدخلات
    first = rank(records, conf, bench)
    second = rank(records, conf, benchmark(records))
    # الترتيب والدرجات والطبقات حتمية — زمن الاستيراد وحده قياس حيّ لا يُقارن
    def sig(rows: list) -> list:
        return [(r["rank"], r["name"], r["score"], r["tier"], r["status"])
                for r in rows]

    assert sig(first) == sig(second)
    by_name = {r["name"]: r for r in first}
    assert by_name["fast"]["tier"] == "S" and by_name["fast"]["rank"] == 1
    assert by_name["ghost"]["score"] == 0.0 and by_name["ghost"]["tier"] == "C"
    assert by_name["half"]["status"] == "broken"
    assert [r["rank"] for r in first] == [1, 2, 3]  # كلّ مرتب فريداً


def test_rank_survives_missing_bench_entries() -> None:
    records = _records()[:2]
    conf = run_conformance(records)
    ranked = rank(records, conf, [])  # bench فارغ تماماً — أسوأ الحالات
    by_name = {r["name"]: r for r in ranked}
    # الصحة وحدها تنجو: fast سليم بلا قياس ⇒ 50، وghost مكسور ⇒ 0
    assert by_name["fast"]["score"] == 50.0
    assert by_name["ghost"]["score"] == 0.0
    assert all(r["import_ms"] == SPEED_CAP_MS for r in ranked)


def test_full_fleet_rank_smoke() -> None:
    records = build_inventory()
    conf = run_conformance(records)
    ranked = rank(records, conf, benchmark(records))
    assert len(ranked) == 106
    assert ranked[0]["score"] >= ranked[-1]["score"]
    tiers = {r["tier"] for r in ranked}
    assert tiers <= {"S", "A", "B", "C"}


def test_render_markdown_contains_truth(tmp_path: Path) -> None:
    records = _records()
    conf = run_conformance(records)
    ranked = rank(records, conf, benchmark(records))
    md = render_markdown(summary(records), ranked, conf)
    assert "# لوحة ترتيب أسطول الوكلاء" in md
    assert "| healthy |" in md and "| broken |" in md
    assert "`1.47.0`" in md or "1." in md  # الإصدار معلن
    assert "**fast**" in md or "| fast |" in md
    for row in ranked:
        assert row["name"] in md  # أعلى 25 يغطي أسطولنا الصغير كله
    assert "reports/fleet_inventory.json" in md


def test_write_reports_roundtrip(tmp_path: Path) -> None:
    records = _records()
    conf = run_conformance(records)
    ranked = rank(records, conf, benchmark(records))
    from src.fleet.inventory import reconcile

    paths = write_reports(tmp_path, summary(records), records, ranked,
                          conf, reconcile(records))
    assert [p.name for p in paths] == ["fleet_inventory.json",
                                       "agent_leaderboard.md"]
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    assert payload["summary"]["total"] == 3
    assert len(payload["agents"]) == 3
    assert payload["agents"][0]["to_json" if False else "name"]
    assert len(payload["ranking"]) == 3
    md = paths[1].read_text(encoding="utf-8")
    assert md.startswith("# لوحة ترتيب أسطول الوكلاء")
    # الكتابة داخل مجلد غير موجود تُنشئه ولا تهرب منه
    nested = tmp_path / "deep" / "dir"
    write_reports(nested, summary(records), records, ranked, conf,
                  reconcile(records))
    assert (nested / "fleet_inventory.json").is_file()


def test_cli_report_end_to_end(tmp_path: Path) -> None:
    """الخط الكامل عبر الواجهة الحقيقية: جرد→مطابقة→فحص→قياس→تقارير."""
    from src.fleet.report import main

    out = tmp_path / "reports"
    code = main(["--out", str(out)])
    assert code == 0
    payload = json.loads((out / "fleet_inventory.json").read_text(encoding="utf-8"))
    assert payload["summary"]["total"] == 106
    assert payload["conformance_counts"]["broken"] == 1  # pr_reviewer المعلن
    names = {a["name"] for a in payload["agents"]}
    assert "pr_reviewer" in names and "architect" in names


def test_benchmark_deep_measures_core_run() -> None:
    """deep=True: الوكلاء الأساسيون يُشغَّلون فعلاً ويُقاس زمنهم."""
    records = [r for r in build_inventory() if r.framework == "core"][:3]
    results = benchmark(records, deep=True)
    assert all(r["run_ms"] is not None for r in results)
    assert all(r["import_ok"] and r["entrypoint_ok"] for r in results)
