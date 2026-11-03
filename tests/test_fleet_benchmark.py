"""اختبارات قياس وترتيب الأسطول — درجات متمايزة معلنة، ترتيب حتمي، طبقات عادلة.

منذ v1.49.0 (ب1.3): الدرجة = صحة 30٪ + استيراد 15٪ + دخول 15٪
+ استدعاء 25٪ + SLO دور 15٪ — ومن لا يُقاس لا يُمنح نقاط استدعاء.
واختبار تقارير النشر: لوحة Markdown + JSON كامل داخل المجلد الممرَّر فقط،
وCLI كامل يُنتج كل شيء بلا شبكة.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.fleet.benchmark import (
    INVOKE_FULL,
    INVOKE_NONE,
    INVOKE_PARTIAL,
    ROLE_SLO_BUDGETS,
    SLO_OVERSHOOT_CAP,
    SCORE_WEIGHTS,
    TIER_THRESHOLDS,
    _decay_component,
    _invoke_component,
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
        AgentRecord(
            name="fast",
            framework="legacy",
            source="a.py",
            module="src.fleet.record",
            symbol="AgentRecord",
            description="ok",
            category="meta",
            criticality="standard",
        ),
        AgentRecord(
            name="ghost",
            framework="legacy",
            source="b.py",
            module="no.such.module_bench",
            symbol="Ghost",
            description="ok",
        ),
        AgentRecord(
            name="half",
            framework="legacy",
            source="record.py",
            module="src.fleet.record",
            symbol="NoSuchSymbol",
            description="ok",
        ),
    ]


def test_weights_and_thresholds_are_declared_sane() -> None:
    """ب1.3: الأوزان الخمسة مجموعها 1.0 والعتبات معلنة."""
    assert sum(SCORE_WEIGHTS.values()) == 1.0
    assert set(SCORE_WEIGHTS) == {"health", "speed", "entry", "invoke", "slo"}
    assert SCORE_WEIGHTS["health"] == 0.30 and SCORE_WEIGHTS["invoke"] == 0.25
    assert SCORE_WEIGHTS["slo"] == 0.15
    assert TIER_THRESHOLDS == {"S": 95.0, "A": 85.0, "B": 70.0}


def test_role_slo_budgets_declared_for_all_roles() -> None:
    """ب1.4: ميزانية استيراد واستدعاء لكل دور، وميزانية الأداة أضيق."""
    assert set(ROLE_SLO_BUDGETS) == {"tool", "manager", "service"}
    for role, budget in ROLE_SLO_BUDGETS.items():
        assert set(budget) == {"import_ms", "run_ms"}, role
        assert 0 < budget["import_ms"] < budget["run_ms"], role
    assert (
        ROLE_SLO_BUDGETS["tool"]["run_ms"]
        < ROLE_SLO_BUDGETS["manager"]["run_ms"]
        < ROLE_SLO_BUDGETS["service"]["run_ms"]
    )


def test_tier_boundaries() -> None:
    assert tier_of(100.0) == "S" and tier_of(95.0) == "S"
    assert tier_of(94.99) == "A" and tier_of(85.0) == "A"
    assert tier_of(84.99) == "B" and tier_of(70.0) == "B"
    assert tier_of(69.99) == "C" and tier_of(0.0) == "C"


def test_decay_component_shape() -> None:
    """منحنى المكوّن: 100 عند الالتزام، 0 عند 3× الميزانية، خطي بينهما."""
    budget = 10.0
    assert _decay_component(0.5, budget) == 100.0
    assert _decay_component(budget, budget) == 100.0
    assert _decay_component(budget * SLO_OVERSHOOT_CAP, budget) == 0.0
    assert _decay_component(budget * SLO_OVERSHOOT_CAP * 10, budget) == 0.0
    mid = _decay_component(budget * 2, budget)
    assert 0.0 < mid < 100.0


def test_invoke_rubric_is_declared() -> None:
    """ميزان الاستدعاء: 100 ناجح، 40 بناء فقط، 0 فشل/غير مقاس."""
    assert INVOKE_FULL == 100.0 and INVOKE_PARTIAL == 40.0
    assert INVOKE_NONE == 0.0
    assert _invoke_component({"call_ok": True}) == INVOKE_FULL
    assert _invoke_component({"call_ok": False, "probe": "construct-only"}) == INVOKE_PARTIAL
    assert _invoke_component({"call_ok": False, "probe": "call-failed:method"}) == INVOKE_NONE
    assert _invoke_component({"call_ok": False}) == INVOKE_NONE


def test_benchmark_marks_broken_and_missing_entry() -> None:
    results = {r["name"]: r for r in benchmark(_records())}
    assert results["fast"]["import_ok"] and results["fast"]["entrypoint_ok"]
    assert not results["ghost"]["import_ok"]  # استيراد ميت
    assert results["half"]["import_ok"]  # الوحدة تعيش
    assert not results["half"]["entrypoint_ok"]  # والرمز غائب
    assert all(r["run_ms"] is None for r in results.values())  # بلا deep
    assert all(r["run_kind"] is None for r in results.values())


def test_rank_is_deterministic_and_weighted() -> None:
    records = _records()
    conf = run_conformance(records)
    bench = benchmark(records)  # القياس الواحد ثابت المدخلات
    first = rank(records, conf, bench)
    second = rank(records, conf, benchmark(records))

    def sig(rows: list) -> list:
        return [(r["rank"], r["name"], r["score"], r["tier"], r["status"]) for r in rows]

    assert sig(first) == sig(second)
    by_name = {r["name"]: r for r in first}
    # سليم ومقاس جزئياً (بلا deep): صحة 30 + سرعة 15 + دخول 15 = 60 — بلا
    # نقاط استدعاء مجانية (صدق معلن: من لا يُقاس لا يُمنح)
    assert by_name["fast"]["score"] == 60.0
    assert by_name["fast"]["tier"] == "C" and by_name["fast"]["rank"] == 1
    assert by_name["ghost"]["score"] == 0.0 and by_name["ghost"]["tier"] == "C"
    assert by_name["half"]["status"] == "broken"
    assert [r["rank"] for r in first] == [1, 2, 3]  # كلّ مرتب فريداً


def test_rank_survives_missing_bench_entries() -> None:
    records = _records()[:2]
    conf = run_conformance(records)
    ranked = rank(records, conf, [])  # bench فارغ تماماً — أسوأ الحالات
    by_name = {r["name"]: r for r in ranked}
    # الصحة وحدها تنجو: fast سليم بلا أي قياس ⇒ 30 (صحة فقط — بلا مجاميل)،
    # وghost مكسور ⇒ 0
    assert by_name["fast"]["score"] == 30.0
    assert by_name["ghost"]["score"] == 0.0
    tool_cap = ROLE_SLO_BUDGETS["tool"]["import_ms"] * SLO_OVERSHOOT_CAP
    assert all(r["import_ms"] == tool_cap for r in ranked)


def test_slo_budget_violation_lowers_tier() -> None:
    """ب1.4: مثال اصطناعي — مخالفة الميزانية تُخفض الطبقة آلياً."""
    tool = ROLE_SLO_BUDGETS["tool"]
    swift = AgentRecord(
        name="swift_tool",
        framework="novamind",
        source="x.py",
        module="src.fleet.record",
        symbol="AgentRecord",
        role="tool",
        description="ok",
    )
    slow = AgentRecord(
        name="slow_tool",
        framework="novamind",
        source="y.py",
        module="src.fleet.record",
        symbol="AgentRecord",
        role="tool",
        description="ok",
    )
    conf = run_conformance([swift, slow])
    bench = [
        {
            "name": "swift_tool",
            "framework": "novamind",
            "import_ms": 0.2,
            "import_ok": True,
            "entrypoint_ok": True,
            "run_ms": 0.5,
            "run_kind": "invoke",
            "call_ok": True,
            "probe": "call:method",
        },
        {
            "name": "slow_tool",
            "framework": "novamind",
            "import_ms": 0.2,
            "import_ok": True,
            "entrypoint_ok": True,
            "run_ms": tool["run_ms"] * SLO_OVERSHOOT_CAP * 100,
            "run_kind": "invoke",
            "call_ok": True,
            "probe": "call:method",
        },
    ]
    ranked = {r["name"]: r for r in rank([swift, slow], conf, bench)}
    assert ranked["swift_tool"]["tier"] == "S"  # ملتزم بالميزانية
    assert ranked["slow_tool"]["tier"] == "A"  # مخالف ⇒ هبوط آلي
    assert ranked["slow_tool"]["slo"] == 0.0
    # والبناء بلا عقد استدعاء أقل من الناجح لكنه ليس صفراً (ميزان معلن)
    builder = dict(bench[0])
    builder["name"] = "builder"
    builder.update(call_ok=False, probe="construct-only", run_ms=0.1, run_kind="construct")
    builder_rec = AgentRecord(
        name="builder",
        framework="novamind",
        source="z.py",
        module="src.fleet.record",
        symbol="AgentRecord",
        role="tool",
        description="ok",
    )
    ranked_b = {
        r["name"]: r for r in rank([builder_rec], run_conformance([builder_rec]), [builder])
    }
    assert ranked_b["builder"]["invoke"] == INVOKE_PARTIAL
    assert ranked_b["builder"]["slo"] == 0.0  # البناء لا يمنح SLO
    assert ranked_b["builder"]["tier"] == "B"  # 30+15+15+10 = 70


def test_same_name_across_frameworks_is_measured_independently() -> None:
    """انحلال تصادم الأسماء المشتركة (ف2): الهوية (إطار، اسم) لا الاسم.

    قبل الإصلاح كان وكيلان يحملان نفس الاسم يتقاسمان قياس الأول في
    ``bench_by_name`` — فيُقاس أحدهما زوراً ويُترك الآخر بلا قياس.
    """
    twin_a = AgentRecord(
        name="twin",
        framework="core",
        source="a.py",
        module="src.fleet.record",
        symbol="AgentRecord",
        role="tool",
        description="ok",
    )
    twin_b = AgentRecord(
        name="twin",
        framework="novamind",
        source="b.py",
        module="src.fleet.record",
        symbol="AgentRecord",
        role="tool",
        description="ok",
    )
    conf = run_conformance([twin_a, twin_b])
    bench = [
        {
            "name": "twin",
            "framework": "core",
            "import_ms": 0.2,
            "import_ok": True,
            "entrypoint_ok": True,
            "run_ms": 0.3,
            "run_kind": "invoke",
            "call_ok": True,
            "probe": "call:method",
        },
        {
            "name": "twin",
            "framework": "novamind",
            "import_ms": 0.2,
            "import_ok": True,
            "entrypoint_ok": True,
            "run_ms": ROLE_SLO_BUDGETS["tool"]["run_ms"] * SLO_OVERSHOOT_CAP,
            "run_kind": "invoke",
            "call_ok": True,
            "probe": "call:method",
        },
    ]
    ranked = {(r["framework"], r["name"]): r for r in rank([twin_a, twin_b], conf, bench)}
    assert ranked[("core", "twin")]["slo"] == 100.0
    assert ranked[("novamind", "twin")]["slo"] == 0.0
    assert ranked[("core", "twin")]["score"] != ranked[("novamind", "twin")]["score"]


def test_full_fleet_rank_smoke() -> None:
    """الأسطول كامل بوضع عميق — التمييز حقيقي لا شطاري (ب1.3).

    الوضع السطحي بلا استدعاء يعطي الجميع 60 (صحة+سرعة+دخول) فلا تمييز —
    التمييز يأتي من القياس الفعلي، وهو ما تفعله تقارير ``--deep``.
    """
    records = build_inventory()
    conf = run_conformance(records)
    ranked = rank(records, conf, benchmark(records, deep=True))
    assert len(ranked) == 106
    assert ranked[0]["score"] >= ranked[-1]["score"]
    tiers = {r["tier"] for r in ranked}
    assert tiers <= {"S", "A", "B", "C"}
    # ب1.3: الإشباع انتهى — التوزيع لم يعد طبقة واحدة، والدرجات متمايزة.
    # بنيوي حتمي: S (المُقاس الملتزم) + B (بناء فقط) + C (غير مُقاس/فاشل)؛
    # واختياري A إن كان أبطأ مُقاس متجاوزاً لميزانيته (test_runner).
    assert len(tiers) >= 3, f"التوزيع ما زال منحلاً: {tiers}"
    scores = {r["score"] for r in ranked}
    assert len(scores) >= 3, "الدرجات ما زالت مشبعة — لا تمييز"
    assert {"S", "B"} <= tiers  # القمة المُقاسة والوسطى البانية كلاهما حاضران


def test_render_markdown_contains_truth(tmp_path: Path) -> None:
    records = _records()
    conf = run_conformance(records)
    ranked = rank(records, conf, benchmark(records))
    md = render_markdown(summary(records), ranked, conf)
    assert "# لوحة ترتيب أسطول الوكلاء" in md
    assert "| healthy |" in md and "| broken |" in md
    assert "`1." in md  # الإصدار معلن
    assert "**fast**" in md or "| fast |" in md
    for row in ranked:
        assert row["name"] in md  # أعلى 25 يغطي أسطولنا الصغير كله
    assert "reports/fleet_inventory.json" in md
    # نموذج الدرجة الجديد والقياس المعلن ظاهران للقارئ
    assert "fake-clock" in md and "SLO" in md
    assert "توزيع الطبقات" in md


def test_write_reports_roundtrip(tmp_path: Path) -> None:
    records = _records()
    conf = run_conformance(records)
    ranked = rank(records, conf, benchmark(records))
    from src.fleet.inventory import reconcile

    paths = write_reports(tmp_path, summary(records), records, ranked, conf, reconcile(records))
    assert [p.name for p in paths] == ["fleet_inventory.json", "agent_leaderboard.md"]
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    assert payload["summary"]["total"] == 3
    assert len(payload["agents"]) == 3
    assert payload["agents"][0]["to_json" if False else "name"]
    assert len(payload["ranking"]) == 3
    md = paths[1].read_text(encoding="utf-8")
    assert md.startswith("# لوحة ترتيب أسطول الوكلاء")
    # الكتابة داخل مجلد غير موجود تُنشئه ولا تهرب منه
    nested = tmp_path / "deep" / "dir"
    write_reports(nested, summary(records), records, ranked, conf, reconcile(records))
    assert (nested / "fleet_inventory.json").is_file()


def test_cli_report_end_to_end(tmp_path: Path) -> None:
    """الخط الكامل عبر الواجهة الحقيقية: جرد→مطابقة→فحص→قياس→تقارير."""
    from src.fleet.report import main

    out = tmp_path / "reports"
    code = main(["--out", str(out)])
    assert code == 0
    payload = json.loads((out / "fleet_inventory.json").read_text(encoding="utf-8"))
    assert payload["summary"]["total"] == 106
    # الصدق بقوائم أسباب لا أعداد ثابتة: pr_reviewer سليم منذ إصلاحه 1.48.1
    # (استيرادات مرنة معلنة)، وnexus_agent وحده حساس بيئياً لغياب
    # sse-starlette إن غابت — فلا يُربط الاختبار بعدد صارم يتقلب بالبيئة.
    names = {a["name"] for a in payload["agents"]}
    assert "pr_reviewer" in names and "architect" in names
    by_name = {r["name"]: r for r in payload["ranking"]}
    assert by_name["pr_reviewer"]["status"] == "healthy"
    for rec in payload["ranking"]:
        if rec["status"] == "broken":
            assert rec["name"] == "nexus_agent", (
                f"مكسور غير معلن: {rec['name']} — أعلنه في قوائم الصدق"
            )


def test_benchmark_deep_measures_core_run() -> None:
    """deep=True: الوكلاء الأساسيون يُشغَّلون فعلاً ويُقاس زمنهم."""
    records = [r for r in build_inventory() if r.framework == "core"][:3]
    results = benchmark(records, deep=True)
    assert all(r["run_ms"] is not None for r in results)
    assert all(r["run_kind"] == "invoke" for r in results)
    assert all(r["mode"] == "fake-clock" for r in results)
    assert all(r["import_ok"] and r["entrypoint_ok"] for r in results)


def test_benchmark_deep_measures_every_novamind_agent() -> None:
    """ب1.2: حقل run_ms غير-``null`` لكل وكلاء novamind الـ79 — الاختبار
    يمنع عودة ``null``؛ والحِمل كله ``mode: fake-clock`` أوفلاين حتمي."""
    records = [r for r in build_inventory() if r.framework == "novamind"]
    assert len(records) == 79
    results = benchmark(records, deep=True)
    assert len(results) == 79
    unmeasured = [r["name"] for r in results if r["run_ms"] is None]
    assert not unmeasured, f"وكلاء بلا قياس: {unmeasured} — أعلن سببهم في حِمل probe"
    for r in results:
        if r["run_kind"] == "invoke":
            assert r["mode"] == "fake-clock", r["name"]
        else:
            assert r["run_kind"] == "construct", r["name"]
        assert r["import_ok"] and r["entrypoint_ok"], r["name"]
    # الصدق: من استُدعي نجح فعلاً، ومن بُني فقط معلن بناءً
    kinds = {r["run_kind"] for r in results}
    assert kinds <= {"invoke", "construct"}
    assert "invoke" in kinds  # الأغلبية قابلة للاستدعاء فعلاً
