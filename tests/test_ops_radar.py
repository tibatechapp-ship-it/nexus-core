"""اختبارات الرادار التشغيلي — العزل والميزانية والساعات الصامتة والملخص."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.ops import OpsStore
from src.ops.radar import (
    DEFAULT_SOURCES,
    RadarConfig,
    RadarSource,
    OpsRadar,
    http_fetch,
    load_config,
    score_item,
)


def _source(sid: str = "s1", cadence: str = "morning",
            keywords: tuple[str, ...] = ()) -> RadarSource:
    """مصدر اختبار واحد — رابط مثبت وكلمات مُمرَّرة."""
    return RadarSource(sid, "code", cadence, "https://example.com/feed", keywords)


class TestRadarSource:
    def test_invalid_fields_rejected(self) -> None:
        """كل حقل خارج الثوابت رفع صريح — المصدر لا يُقبل على تخمين."""
        with pytest.raises(ValueError, match="المصدر"):
            RadarSource("", "code", "morning", "https://x")
        with pytest.raises(ValueError, match="نوع"):
            RadarSource("s", "crypto", "morning", "https://x")
        with pytest.raises(ValueError, match="فترة"):
            RadarSource("s", "code", "hourly", "https://x")
        with pytest.raises(ValueError, match="HTTP"):
            RadarSource("s", "code", "morning", "ftp://x")


class TestRadarConfig:
    def test_bounds_enforced(self) -> None:
        """السقوف محكومة — ميزانية ونافذة وساعات خارج المدى رفع."""
        with pytest.raises(ValueError, match="الميزانية"):
            RadarConfig(max_items_per_run=0)
        with pytest.raises(ValueError, match="نافذة"):
            RadarConfig(dedup_window_days=-1)
        with pytest.raises(ValueError, match="Top-N"):
            RadarConfig(top_n=0)
        with pytest.raises(ValueError, match="الساعات"):
            RadarConfig(quiet_hours=(25,))


class TestScoreItem:
    def test_keyword_weights_accumulate(self) -> None:
        """الدرجات تتراكم بالكلمات — وكيل وLLM أعلى من كلمة واحدة."""
        low = score_item("a plain tool")
        high = score_item("new agent llm")
        assert high > low
        assert score_item("LLM AGENT", (), ()) > 0

    def test_extra_keywords_count(self) -> None:
        """كلمات المصدر الخاصة تُحتسب بوزنها إن لم تكن في العام."""
        assert score_item("mizan scanner", (), ("mizan",)) > 0


class TestCatalog:
    def test_fourteen_sources_declared(self) -> None:
        """الكتالوج 14 مصدرًا معلنًا — تغييره قرار بيان مُختبَر."""
        assert len(DEFAULT_SOURCES) == 14
        ids = [s.id for s in DEFAULT_SOURCES]
        assert len(ids) == len(set(ids))

    def test_cadences_cover_both_cycles(self) -> None:
        """كل فترة لها مصادر نشطة — لا دورة صباحية فارغة."""
        assert any(s.cadence in {"morning", "both"} for s in DEFAULT_SOURCES)
        assert any(s.cadence in {"evening", "both"} for s in DEFAULT_SOURCES)


class TestOpsRadarRun:
    def test_catalog_only_run_touches_no_network(self) -> None:
        """الكتالوغي بلا مُجلب: كل المصادر سليمة وصفر عناصر — بلا شبكة."""
        radar = OpsRadar(OpsStore(":memory:"))
        result = radar.run("morning")
        assert result.sources_ok and result.items_seen == 0
        assert not result.sources_failed and not result.skipped_quiet

    def test_invalid_cadence_rejected(self) -> None:
        """فترة غير معروفة رفع — الدورتان المعلنتان فقط."""
        radar = OpsRadar(OpsStore(":memory:"))
        with pytest.raises(ValueError, match="الفترة"):
            radar.run("weekly")

    def test_quiet_hour_skips_and_audits(self) -> None:
        """الساعة الصامتة تؤجل الدورة بعلم صريح وسطر تدقيق — لا جلب ليلي."""
        store = OpsStore(":memory:")
        radar = OpsRadar(store)
        result = radar.run("morning", fetcher=lambda s: [], now_hour=3)
        assert result.skipped_quiet
        assert any(e["action"] == "radar.skipped_quiet" for e in store.tail_audit(5))

    def test_per_source_failure_isolated(self) -> None:
        """فشل مصدر لا يوقف البقية — الخطأ مسجّل وسطر تدقيق مكتوب."""
        store = OpsStore(":memory:")
        srcs = (_source("ok"), _source("bad"))
        radar = OpsRadar(store, sources=srcs)

        def fetcher(src: RadarSource) -> list[dict[str, Any]]:
            if src.id == "bad":
                raise IOError("انقطاع")
            return [{"title": "agent tool", "url": "https://x/a"}]

        result = radar.run("morning", fetcher=fetcher)
        assert result.sources_ok == ["ok"]
        assert "bad" in result.sources_failed
        assert result.items_stored == 1
        assert any(e["action"] == "radar.source_failed"
                   for e in store.tail_audit(10))

    def test_normalize_skips_malformed_and_remote_schemes(self) -> None:
        """العناصر المشوّهة وغير HTTP تُهمَل — لا إشارة بلا عنوان سليم."""
        store = OpsStore(":memory:")
        radar = OpsRadar(store, sources=(_source("s"),))
        items = [
            {"title": "", "url": "https://x/1"},
            {"title": "t", "url": ""},
            {"title": "t", "url": "javascript:alert(1)"},
        ]
        result = radar.run("morning", fetcher=lambda s: items)
        assert result.items_seen == 0 and result.items_stored == 0

    def test_budget_and_min_score_gates(self) -> None:
        """الميزانية سقف قاسٍ والدرجة الدنيا مرشّح — الزائد يُعدّ ولا يُخزَّن."""
        store = OpsStore(":memory:")
        cfg = RadarConfig(max_items_per_run=2, min_score=1.0)
        radar = OpsRadar(store, cfg, sources=(_source("s"),))
        items = [
            {"title": "agent one", "url": "https://x/1"},
            {"title": "agent two", "url": "https://x/2"},
            {"title": "agent three", "url": "https://x/3"},
        ]
        result = radar.run("morning", fetcher=lambda s: items)
        assert result.items_stored == 2
        assert result.items_below_budget == 1

    def test_dedup_window_applied(self) -> None:
        """نفس العنصر في دورتين يُخزَّن مرة — الثانية مُعَدّة مكررًا."""
        store = OpsStore(":memory:")
        radar = OpsRadar(store, sources=(_source("s"),))
        items = [{"title": "agent tool", "url": "https://x/dup"}]
        r1 = radar.run("morning", fetcher=lambda s: items)
        r2 = radar.run("morning", fetcher=lambda s: items)
        assert r1.items_stored == 1 and r2.items_deduped == 1

    def test_digest_written_with_top_signals(self) -> None:
        """كل دورة تنتج ملخصًا واحدًا — أعلى الإشارات في نصه."""
        store = OpsStore(":memory:")
        radar = OpsRadar(store, RadarConfig(top_n=2), sources=(_source("s"),))
        items = [
            {"title": "agent llm sandbox", "url": "https://x/top"},
            {"title": "plain", "url": "https://x/low", "score": 0.0},
        ]
        radar.run("morning", fetcher=lambda s: items)
        digest = store.latest_digest("morning")
        assert digest is not None
        summary = digest.payload["summary"]
        assert "https://x/top" in summary and "المصادر السليمة" in summary


class TestLoadConfig:
    def test_none_returns_defaults(self) -> None:
        """بلا ملف إعدادات: الافتراضيات كما هي — لا افتراض مخفي."""
        assert load_config(None) == RadarConfig()

    def test_partial_file_merges(self, tmp_path: Path) -> None:
        """الملف الجزئي يُدمج مع الافتراضات — المفاتيح الغريبة تُهمَل."""
        f = tmp_path / "cfg.json"
        f.write_text(json.dumps({"top_n": 3, "unknown_key": 1}), encoding="utf-8")
        cfg = load_config(str(f))
        assert cfg.top_n == 3 and cfg.max_items_per_run == RadarConfig().max_items_per_run

    def test_non_object_file_rejected(self, tmp_path: Path) -> None:
        """ملف إعدادات ليس كائنًا رفع صريح — قائمة لا تُقبل."""
        f = tmp_path / "bad.json"
        f.write_text("[]", encoding="utf-8")
        with pytest.raises(ValueError, match="كائن"):
            load_config(str(f))


class TestHttpFetch:
    def test_offline_failure_raises_for_isolation(self) -> None:
        """المُجلب الحي في بيئة بلا شبكة يفشل — الدورة هي التي تعزله."""
        src = _source("offline")
        with pytest.raises(Exception):
            http_fetch(src, timeout=1)
