"""اختبارات رادار التوليد — تقرير الصباح والمساء.

العقد المفحوص: كتالوج معلن (14 مصدراً على الأقل)، فترتان صحيحتان،
تقرير حتمي قابل للمقارنة، وجلب حي معزول لا يهدم ولا يتصل بالشبكة.
"""

from __future__ import annotations

import json

import pytest

from src.novamind.ops.radar import (
    CADENCES, KINDS, Radar, RadarSource, DEFAULT_CATALOG, live_digest,
)


# ── الكتالوج ─────────────────────────────────────────────────────────

def test_catalog_has_at_least_fourteen_sources():
    assert len(DEFAULT_CATALOG) >= 14


def test_catalog_names_are_unique():
    names = [s.name for s in DEFAULT_CATALOG]
    assert len(names) == len(set(names))


def test_catalog_kinds_cover_all_four():
    kinds = {s.kind for s in DEFAULT_CATALOG}
    assert kinds == set(KINDS)


def test_invalid_kind_is_rejected():
    with pytest.raises(ValueError, match="kind"):
        RadarSource("x", "X", "unknown-kind", "morning", "https://x", "ب")


def test_invalid_cadence_is_rejected():
    with pytest.raises(ValueError, match="cadence"):
        RadarSource("x", "X", "code", "noon", "https://x", "ب")


def test_duplicate_name_in_custom_catalog_is_rejected():
    dup = RadarSource("github", "GitHub", "code", "both", "u", "ب")
    with pytest.raises(ValueError, match="مكرر"):
        Radar(catalog=[dup, dup])


# ── الفترتان ─────────────────────────────────────────────────────────

def test_sources_for_morning_includes_new_morning_sources():
    radar = Radar()
    names = {s.name for s in radar.sources_for("morning")}
    for required in ("npm", "pypi", "producthunt", "kaggle", "ollama", "github"):
        assert required in names, f"مصدر الصباح ناقص: {required}"


def test_sources_for_evening_includes_evening_sources():
    radar = Radar()
    names = {s.name for s in radar.sources_for("evening")}
    for required in ("dockerhub", "replicate", "gitee", "sourceforge", "bitbucket"):
        assert required in names, f"مصدر المساء ناقص: {required}"


def test_both_cadence_sources_appear_in_both_periods():
    radar = Radar()
    m = {s.name for s in radar.sources_for("morning")}
    e = {s.name for s in radar.sources_for("evening")}
    both = {s.name for s in radar.sources if s.cadence == "both"}
    assert both <= (m & e)


def test_unknown_cadence_raises_everywhere():
    radar = Radar()
    with pytest.raises(ValueError, match="فترة"):
        radar.sources_for("noon")
    with pytest.raises(ValueError, match="فترة"):
        radar.report("noon")
    with pytest.raises(ValueError, match="فترة"):
        live_digest(radar, None, "noon")


# ── التقرير الحتمي ───────────────────────────────────────────────────

def test_report_is_deterministic_without_stamp():
    radar = Radar()
    assert radar.report("morning") == radar.report("morning")
    assert radar.report("evening") == radar.report("evening")


def test_report_contains_sections_and_benefit_column():
    text = Radar().report("morning")
    assert "تقرير الصباح" in text
    assert "| المصدر | الرابط | المستفاد |" in text
    assert "مستودعات ومشاريع" in text
    assert "نماذج الذكاء" in text


def test_report_counts_declared_total():
    radar = Radar()
    text = radar.report("morning")
    total = len(radar.sources_for("morning"))
    assert f"**{total} مصدراً**" in text


def test_report_with_stamp_differs_only_in_header():
    radar = Radar()
    base = radar.report("morning")
    stamped = radar.report("morning", generated_at="2026-11-14 09:00 UTC")
    assert "2026-11-14 09:00 UTC" in stamped
    assert stamped.replace("*أُنشئ: 2026-11-14 09:00 UTC*\n\n", "", 1) == base


def test_snapshot_json_is_sorted_and_loadable():
    radar = Radar()
    data = json.loads(radar.snapshot())
    names = [d["name"] for d in data]
    assert len(names) == len(set(names))  # بلا تكرار
    assert all(d["benefit"] and d["url"].startswith("https://") for d in data)


# ── الجلب الحي المعزول ───────────────────────────────────────────────

def test_live_digest_without_fetcher_is_catalog_only():
    out = live_digest(Radar(), None, "morning")
    assert out and all(d["status"] == "catalog" for d in out)


def test_live_digest_with_injected_fetcher_marks_success():
    radar = Radar()
    out = live_digest(radar, lambda s: f"آخر {s.label}", "morning")
    ok = [d for d in out if d["status"] == "ok"]
    assert ok and all(d["digest"].startswith("آخر") for d in ok)


def test_live_digest_unavailable_is_declared_not_raised():
    radar = Radar()

    def failing_fetcher(s):
        raise RuntimeError("لا شبكة")

    out = live_digest(radar, failing_fetcher, "evening")
    assert out, "القائمة لا تُفرَّغ أبداً"
    assert all(d["status"] == "unavailable" for d in out)
    assert all(d["digest"] == "RuntimeError" for d in out)


def test_live_digest_none_result_is_unavailable():
    out = live_digest(Radar(), lambda s: None, "morning")
    assert all(d["status"] == "unavailable" for d in out)
