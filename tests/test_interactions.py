"""Phase 1 unit tests — long-term interaction memory + self-reflection.

Fully offline/hermetic: temp SQLite files, injected clocks, monkeypatched
environments.  Covers :mod:`src.learning.interactions` (store, path chain,
similarity, stats, singleton) and :mod:`src.learning.reflection` (prompt
builders, tolerant parser, retry rule, awareness-gap matrix, memory block).
"""
from __future__ import annotations

import pytest

from src.learning.interactions import (
    InteractionStore,
    default_interaction_db_path,
    get_interaction_store,
    reset_interaction_store,
)
from src.learning.reflection import (
    RATINGS,
    RETRY_GRACE,
    awareness_gap,
    build_reflection_prompt,
    build_retry_system,
    memory_block,
    parse_reflection,
    rating_score,
    should_retry,
)


# ── path resolution ─────────────────────────────────────────────────────────

def test_db_path_prefers_the_dedicated_env(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_INTERACTIONS_DB", str(tmp_path / "x.db"))
    monkeypatch.setenv("NEXUS_DB", str(tmp_path / "other.db"))
    assert default_interaction_db_path() == str(tmp_path / "x.db")


def test_db_path_falls_back_to_a_nexus_db_sibling(monkeypatch, tmp_path):
    monkeypatch.delenv("NEXUS_INTERACTIONS_DB", raising=False)
    monkeypatch.setenv("NEXUS_DB", str(tmp_path / "sessions.db"))
    assert default_interaction_db_path() == str(tmp_path / "interactions.db")


def test_db_path_ends_at_the_repo_data_dir(monkeypatch):
    monkeypatch.delenv("NEXUS_INTERACTIONS_DB", raising=False)
    monkeypatch.delenv("NEXUS_DB", raising=False)
    path = default_interaction_db_path()
    assert path.endswith("data/interactions.db")


# ── store: schema + save + count/stats ──────────────────────────────────────

def test_schema_is_idempotent_and_versioned(tmp_path):
    p = str(tmp_path / "ix.db")
    a = InteractionStore(p)
    b = InteractionStore(p)  # same file, CREATE IF NOT EXISTS + user_version
    assert a.path == p and b.path == p
    assert a.count() == 0


def test_save_returns_the_row_id_and_defaults_empty_fields(tmp_path):
    store = InteractionStore(str(tmp_path / "ix.db"), clock=lambda: 1000.0)
    row_id = store.save(
        agent_id="", question=None, answer=None, signal_ok=True,
        self_rating="good", reflection_reason="واضح",
    )
    assert row_id == 1
    (row,) = store.recent()
    assert row["agent_id"] == "default"
    assert row["question"] == "" and row["answer"] == ""
    assert row["signal_ok"] == 1 and row["self_rating"] == "good"
    assert row["created_at"] == 1000.0


def test_save_normalises_booleans_and_nulls(tmp_path):
    store = InteractionStore(str(tmp_path / "ix.db"))
    store.save(agent_id="coder", question="q", answer="a",
               signal_ok=False, retry_used=True)
    (row,) = store.recent()
    assert row["signal_ok"] == 0 and row["retry_used"] == 1
    assert row["self_rating"] is None and row["awareness_gap"] is None


def test_count_and_stats_on_an_empty_store(tmp_path):
    store = InteractionStore(str(tmp_path / "ix.db"))
    assert store.count() == 0
    stats = store.stats()
    assert stats["count"] == 0
    assert stats["by_rating"] == {
        "excellent": 0, "good": 0, "poor": 0, "unrated": 0,
    }
    assert stats["retries"] == 0 and stats["awareness_gaps"] == 0


def test_stats_aggregates_ratings_retries_and_gaps(tmp_path):
    store = InteractionStore(str(tmp_path / "ix.db"))
    store.save(agent_id="a", question="q1", answer="a1", signal_ok=True,
               self_rating="excellent")
    store.save(agent_id="a", question="q2", answer="a2", signal_ok=False,
               self_rating="good", awareness_gap=1)
    store.save(agent_id="b", question="q3", answer="a3", signal_ok=True,
               self_rating="poor", retry_used=True, retried_rating="good")
    store.save(agent_id="b", question="q4", answer="a4", signal_ok=True)
    stats = store.stats()
    assert stats["count"] == 4
    assert stats["by_rating"] == {
        "excellent": 1, "good": 1, "poor": 1, "unrated": 1,
    }
    assert stats["retries"] == 1 and stats["awareness_gaps"] == 1


# ── store: recent ───────────────────────────────────────────────────────────

def test_recent_is_newest_first_and_filters_by_agent(tmp_path):
    store = InteractionStore(str(tmp_path / "ix.db"), clock=lambda: 1.0)
    store.save(agent_id="a", question="q1", answer="a", signal_ok=True)
    store.save(agent_id="b", question="q2", answer="a", signal_ok=True)
    store.save(agent_id="a", question="q3", answer="a", signal_ok=True)
    all_rows = store.recent()
    assert [r["question"] for r in all_rows] == ["q3", "q2", "q1"]
    only_a = store.recent(agent_id="a")
    assert [r["question"] for r in only_a] == ["q3", "q1"]


@pytest.mark.parametrize(
    ("limit", "expected"),
    [(None, 20), (0, 20), (2, 2), (500, 200), (-5, 1)],
)
def test_recent_clamps_its_limit(tmp_path, limit, expected):
    store = InteractionStore(str(tmp_path / "ix.db"), clock=lambda: 1.0)
    for i in range(210):
        store.save(agent_id="a", question=f"q{i}", answer="a",
                   signal_ok=True)
    rows = store.recent(limit)  # type: ignore[arg-type]
    assert len(rows) == expected


# ── store: similarity recall ────────────────────────────────────────────────

def test_similar_returns_nothing_for_empty_or_tokenless_questions(tmp_path):
    store = InteractionStore(str(tmp_path / "ix.db"))
    store.save(agent_id="a", question="اكتب دالة تحقق", answer="نعم",
               signal_ok=True)
    assert store.similar("") == []
    assert store.similar("؟،؛!!!") == []


def test_similar_ranks_by_query_coverage_and_keeps_successful_only(tmp_path):
    store = InteractionStore(str(tmp_path / "ix.db"), clock=lambda: 5.0)
    # full coverage (4/4), failed run, empty answer, no-overlap → all filtered
    # or outranked
    store.save(agent_id="a", question="اكتب دالة تحقق قوية",
               answer="استخدم hmac.compare_digest", signal_ok=True)
    store.save(agent_id="a", question="كيف أكتب دالة تحقق من كلمة السر؟",
               answer="لا تستخدم md5 أبداً", signal_ok=True)
    store.save(agent_id="a", question="اكتب دالة تحقق قوية",
               answer="فشل فني", signal_ok=False)
    store.save(agent_id="a", question="اكتب دالة تحقق قوية",
               answer="", signal_ok=True)
    store.save(agent_id="a", question="نصيحة عن الطقس", answer="مشمس",
               signal_ok=True)
    rows = store.similar("اكتب دالة تحقق قوية")
    assert len(rows) == 2  # الفاشلة والفارغة مستثناة، والطقس بلا تداخل
    assert rows[0]["answer"] == "استخدم hmac.compare_digest"
    assert rows[0]["score"] == 1.0  # تغطية كاملة للسؤال الجديد
    assert rows[1]["score"] == 0.75  # 3 من 4 رموز مشتركة


def test_similar_breaks_score_ties_by_recency(tmp_path):
    clock = iter([10.0, 20.0, 30.0])
    store = InteractionStore(str(tmp_path / "ix.db"), clock=lambda: next(clock))
    store.save(agent_id="a", question="اكتب دالة تحقق", answer="الأولى",
               signal_ok=True)
    store.save(agent_id="a", question="اكتب دالة تحقق", answer="الثانية",
               signal_ok=True)
    rows = store.similar("اكتب دالة تحقق")
    assert [r["answer"] for r in rows] == ["الثانية", "الأولى"]
    assert rows[0]["score"] == rows[1]["score"] == 1.0


def test_similar_can_filter_by_agent_and_honours_k(tmp_path):
    clock = iter([10.0, 20.0])
    store = InteractionStore(str(tmp_path / "ix.db"), clock=lambda: next(clock))
    store.save(agent_id="coder", question="اكتب دالة تحقق", answer="c",
               signal_ok=True)
    store.save(agent_id="analyst", question="اكتب دالة تحقق", answer="an",
               signal_ok=True)
    # نفس التغطية ⇒ الفرق بالحداثة: الأحدث أولاً
    assert store.similar("اكتب دالة تحقق", k=1)[0]["agent_id"] == "analyst"
    only_coder = store.similar("اكتب دالة تحقق", agent_id="coder")
    assert [r["agent_id"] for r in only_coder] == ["coder"]
    assert store.similar("اكتب دالة تحقق", k=0) == []
    assert store.similar("اكتب دالة تحقق", k=-3) == []


# ── store: singleton ────────────────────────────────────────────────────────

def test_singleton_is_sticky_until_reset(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_INTERACTIONS_DB", str(tmp_path / "s.db"))
    reset_interaction_store()
    try:
        first = get_interaction_store()
        assert get_interaction_store() is first  # first path wins
    finally:
        reset_interaction_store()
    second = get_interaction_store()  # noqa: F841 — a fresh instance
    assert second is not first
    reset_interaction_store()


# ── reflection: prompt builders ─────────────────────────────────────────────

def test_reflection_prompt_truncates_long_inputs():
    prompt = build_reflection_prompt("س" * 3000, "ج" * 5000)
    assert "س" * 2000 in prompt and "س" * 2001 not in prompt
    assert "ج" * 4000 in prompt and "ج" * 4001 not in prompt


def test_reflection_prompt_tolerates_empty_inputs():
    prompt = build_reflection_prompt("", "")
    assert "قيّم الإجابة" in prompt


def test_retry_system_without_a_reason_carries_the_shared_grace_note():
    out = build_retry_system("SYSTEM", None)
    assert out == "SYSTEM" + RETRY_GRACE


def test_retry_system_embeds_and_clips_the_critics_reason():
    out = build_retry_system("SYSTEM", "  غير واضح  ")
    assert "(غير واضح)" in out
    long = build_retry_system("SYSTEM", "x" * 1000)
    assert "x" * 300 in long and "x" * 301 not in long


# ── reflection: tolerant parser ─────────────────────────────────────────────

def test_parse_reflection_handles_the_json_contract():
    rating, reason = parse_reflection(
        'قليلاً: {"rating": "poor", "reason": "أمثلة ناقصة"} شكراً')
    assert rating == "poor" and reason == "أمثلة ناقصة"


def test_parse_reflection_falls_back_to_keywords_on_broken_json():
    # قوسان موجودان لكن JSON مكسور (فاصلة زائدة) ⇒ except → مسح خام
    rating, reason = parse_reflection('{"rating": "poor",}')
    assert rating == "poor" and reason is None


def test_parse_reflection_scans_the_raw_text_when_the_json_lacks_a_rating():
    # "ممتاز" عربي ومعروف ⇒ المسار الناجح (JSON) لا الـfallback
    assert parse_reflection('{"rating": "ممتاز", "reason": "ok"}') == (
        "excellent", "ok")
    # rating غير معروف في JSON صالح ⇒ يُمسح النصّ الخامّ بالكلمات المفتاحية
    rating, reason = parse_reflection(
        '{"rating": "meh", "reason": "الإجابة ركيكة جداً"}')
    assert rating == "poor" and reason is None


def test_parse_reflection_is_empty_and_case_tolerant():
    assert parse_reflection("") == (None, None)
    assert parse_reflection("   ") == (None, None)
    assert parse_reflection('{"rating": "GOOD", "reason": "ok"}') == (
        "good", "ok")
    # rating فارغ داخل JSON ⇒ _find_rating("") ثم مسح النصّ الخام
    assert parse_reflection('{"rating": "", "note": "الجواب ضعيف"}') == (
        "poor", None)


def test_parse_reflection_clips_a_long_reason_to_500():
    _rating, reason = parse_reflection(
        '{"rating": "poor", "reason": "' + "ز" * 900 + '"}')
    assert reason is not None and len(reason) == 500


def test_parse_reflection_prefers_excellent_over_poor_when_both_appear():
    # أولوية المعجم: excellent قبل poor قبل good
    rating, _ = parse_reflection("ممتاز رغم بعض الرداءة الظاهرة")
    assert rating == "excellent"
    rating, _ = parse_reflection("ضعيف جداً رغم قبول جزئي")
    assert rating == "poor"


def test_find_rating_rejects_blank_text():
    assert parse_reflection("لا شيء هنا إطلاقاً") == (None, None)


# ── reflection: scoring + retry rule ────────────────────────────────────────

@pytest.mark.parametrize(("rating", "score"), [
    ("excellent", 1.0), ("good", 0.75), ("poor", 0.4),
    (None, None), ("meh", None),
])
def test_rating_score_maps_only_the_three_known_classes(rating, score):
    assert rating_score(rating) == score


def test_should_retry_fires_only_for_poor():
    assert tuple(RATINGS) == ("excellent", "good", "poor")
    assert should_retry("poor") is True
    assert should_retry("good") is False
    assert should_retry("excellent") is False
    assert should_retry(None) is False


# ── reflection: awareness-gap matrix ────────────────────────────────────────

def test_awareness_gap_is_a_gap_when_it_claims_good_after_a_failure():
    assert awareness_gap("good", signal_ok=False) == 1
    assert awareness_gap("excellent", signal_ok=False) == 1


def test_awareness_gap_is_aligned_when_it_knew_the_answer_was_weak():
    assert awareness_gap("poor", signal_ok=False) == 0
    assert awareness_gap("poor", signal_ok=True, retry_rating="good") == 0
    assert awareness_gap("poor", signal_ok=True,
                         retry_rating="excellent") == 0


def test_awareness_gap_is_not_judgeable_in_the_normal_cases():
    assert awareness_gap(None, signal_ok=True) is None
    assert awareness_gap(None, signal_ok=False) is None
    assert awareness_gap("good", signal_ok=True) is None
    assert awareness_gap("poor", signal_ok=True) is None  # بلا إعادة محاولة


# ── reflection: memory block ────────────────────────────────────────────────

def test_memory_block_is_empty_without_rows():
    assert memory_block([]) == ""


def test_memory_block_lists_rows_with_defaults_and_a_header():
    block = memory_block([
        {"question": "كيف أتحقق؟", "answer": "hmac",
         "self_rating": None, "agent_id": None},
    ])
    assert "ذاكرة الميدان" in block
    assert "[-" in block and "بدون تقييم" in block
    assert "hmac" in block


def test_memory_block_clips_and_collapses_whitespace():
    block = memory_block([{
        "question": "س" * 300, "answer": "ن" * 500,
        "self_rating": "good", "agent_id": "coder",
    }])
    assert "ن" * 399 in block and "ن" * 400 not in block  # قصّ 400 مع "…"
    assert "س" * 199 in block and "س" * 200 not in block  # السؤال يُقصّ عند 200
    block2 = memory_block([{"question": "ق   و\nة", "answer": "a",
                            "self_rating": None, "agent_id": None}])
    assert "ق و" in block2  # المسافات/الأسطر تُدمج


def test_memory_block_honours_its_limit():
    rows = [{"question": f"q{i}", "answer": f"a{i}"} for i in range(5)]
    block = memory_block(rows, limit=2)
    assert "q0" in block and "q1" in block and "q2" not in block
    assert memory_block(rows, limit=0) == ""
