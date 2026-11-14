"""اختبارات فهرس الذكاء — التهذيب والتقطيع والتضمين والاسترجاع بالميزانية."""

from __future__ import annotations

import time

import pytest

from src.ops import OpsStore
from src.ops.indexer import (
    IndexConfig,
    OpsIndex,
    chunk_text,
    cosine,
    embed,
    sanitize,
)


class TestSanitize:
    def test_secrets_replaced_by_tag(self) -> None:
        """كل نمط سر يُستبدل بوسمه — لا سر يدخل الفهرس حرفيًا."""
        fake_jwt = ("eyJ" + "A" * 20 + "." + "eyJ" + "B" * 20 +
                    "." + "C" * 20)
        text = ("key sk-abcdefghijklmnop123456 ghp_" + "a" * 30 +
                " AKIAIOSFODNN7EXAMPLE " + fake_jwt)
        cleaned, removed = sanitize(text)
        assert "sk-" not in cleaned and "ghp_" not in cleaned
        assert "AKIA" not in cleaned and "eyJ" not in cleaned
        assert removed["api_key"] == 1 and removed["github_token"] == 1
        assert removed["aws_key"] == 1 and removed["jwt"] == 1

    def test_pii_email_phone(self) -> None:
        """البريد والهاتف يُهذَّبان — بيانات الهوية بلا استثناء."""
        cleaned, removed = sanitize("اكتب إلى sara@example.com أو 0512345678")
        assert "sara@example.com" not in cleaned
        assert "0512345678" not in cleaned
        assert removed["email"] == 1 and removed["phone"] == 1

    def test_inline_secret_assignment(self) -> None:
        """التخصيصات المفتاحية تُهذَّب — password= وtoken= بكل صورها."""
        cleaned, removed = sanitize("config: password=hunter2 and TOKEN=abc123")
        assert "hunter2" not in cleaned and "abc123" not in cleaned
        assert removed["inline_secret"] == 2

    def test_clean_text_untouched(self) -> None:
        """النص النظيف يمر كما هو — التهذيب لا يشوّه المحتوى السليم."""
        text = "نص تقني سليم عن الوكلاء والذاكرة."
        cleaned, removed = sanitize(text)
        assert cleaned == text and removed == {}


class TestChunk:
    def test_short_text_single_chunk(self) -> None:
        """النص القصير شريحة واحدة — لا تقطيع بلا داعٍ."""
        chunks = chunk_text("فقرة واحدة قصيرة.")
        assert len(chunks) == 1 and chunks[0].index == 0

    def test_long_paragraphs_packed_to_target(self) -> None:
        """الفقرات تُغلف حتى الهدف — الشرائح داخل السقف المعلن."""
        text = "\n\n".join("كلمة " * 100 for _ in range(5))
        chunks = chunk_text(text, target=120, min_tokens=30)
        assert all(c.tokens <= 240 for c in chunks)
        assert len(chunks) >= 2

    def test_small_tail_merged_into_previous(self) -> None:
        """القصاصة الأضعف من الحد الأدنى تُدمج — لا ذيل بلا سياق."""
        text = "أول " * 150 + "\n\n" + "ذيل قصير"
        chunks = chunk_text(text, target=120, min_tokens=200)
        assert len(chunks) == 1

    def test_empty_text_no_chunks(self) -> None:
        """النص الفارغ لا شرائح له — صفر إدخال صادق."""
        assert chunk_text("") == []
        assert chunk_text("\n\n  \n\n") == []

    def test_invalid_target_rejected(self) -> None:
        """هدف التقطيع أقل من 1 رفع — لا سقف بلا معنى."""
        with pytest.raises(ValueError, match="هدف"):
            chunk_text("نص", target=0)

    def test_giant_paragraph_split_by_sentences(self) -> None:
        """الفقرة الضخمة تُقسم بالجمل — بلا فقد نص وبلا تجاوز مخزون."""
        text = ("جملة قصيرة هنا. " * 80).strip()
        chunks = chunk_text(text, target=60, min_tokens=10)
        assert len(chunks) >= 2
        assert sum(c.tokens for c in chunks) >= 160


class TestEmbed:
    def test_deterministic_and_normalized(self) -> None:
        """المتجه حتمي ومطبّع — نفس النص متجه واحد في كل جهاز."""
        v1 = embed("وكلاء LLM", 64)
        v2 = embed("وكلاء LLM", 64)
        assert v1 == v2
        assert abs(sum(x * x for x in v1) - 1.0) < 0.01

    def test_different_texts_different_vectors(self) -> None:
        """النصان المختلفان متجهان مختلفان — التمييز شرط الاسترجاع."""
        assert embed("وكلاء", 32) != embed("ذاكرة", 32)

    def test_empty_text_zero_vector(self) -> None:
        """النص الفارغ متجه صفري بلا انفجار قسمة — التطبيع يحرسه."""
        assert embed("", 16) == tuple([0.0] * 16)

    def test_dims_lower_bound(self) -> None:
        """الأبعاد أقل من 1 رفع — لا تضمين بلا بُعد."""
        with pytest.raises(ValueError, match="الأبعاد"):
            embed("نص", 0)


class TestCosine:
    def test_self_similarity_one(self) -> None:
        """التشابه مع النفس 1.0 — المعايرة المثبتة."""
        v = embed("نص محدد", 32)
        assert cosine(v, v) == 1.0

    def test_clipped_to_unit_range(self) -> None:
        """التشابه مقصوص على [0,1] — القيم خارجها مستحيلة."""
        assert cosine(tuple([2.0] * 8), tuple([2.0] * 8)) == 1.0
        assert cosine(tuple([1.0] * 8), tuple([-1.0] * 8)) == 0.0


@pytest.fixture()
def index() -> OpsIndex:
    """فهرس صغير بمخزن ذاكرة — أبعاد مضغوطة لسرعة الاختبار."""
    return OpsIndex(OpsStore(":memory:"), IndexConfig(dims=64, chunk_target=80,
                                                      chunk_min=20))


class TestIngest:
    def test_ingest_reports_slices_and_redactions(self, index: OpsIndex) -> None:
        """الإدخال يبلّغ الشرائح والتوكن وما مُهذَّب — تقرير صادق كامل."""
        text = ("مرحبا ali@example.com مع مفتاح sk-abcdefghij1234567.\n\n"
                "فقرة تقنية عن الوكلاء والذاكرة والتعلم الإجرائي في الأسطول.")
        r = index.ingest_text(text, "doc1", acl="team:ai")
        assert r["slices"] >= 1 and r["tokens"] > 0
        assert r["removed"]["email"] == 1

    def test_reingest_replaces_slices(self, index: OpsIndex) -> None:
        """إعادة الإدخال تستبدل شرائح المستند — الإصدار الأخير يفوز."""
        index.ingest_text("نسخة أولى طويلة بعض الشيء للشريحة.", "doc")
        index.ingest_text("نسخة ثانية مختلفة تمامًا عن الأولى.", "doc")
        rows = index._store._conn.execute(
            "SELECT body FROM slices WHERE doc_id = 'doc'"
        ).fetchall()
        assert len(rows) == 1
        assert "مختلفة تمامًا" in rows[0]["body"]
        assert "نسخة أولى" not in rows[0]["body"]

    def test_invalid_doc_id_and_acl(self, index: OpsIndex) -> None:
        """معرّف المستند والصلاحية نصان إلزاميان — فارغهما رفع."""
        with pytest.raises(ValueError, match="doc_id"):
            index.ingest_text("نص", " ")
        with pytest.raises(ValueError, match="acl"):
            index.ingest_text("نص", "d", acl="")
        with pytest.raises(ValueError, match="ttl_days"):
            index.ingest_text("نص", "d", ttl_days=-1)

    def test_ingest_file(self, index: OpsIndex, tmp_path: object) -> None:
        """إدخال ملف نصي كامل بالسقف المعلن — الغائب والضخم خطأ صريح."""
        f = tmp_path / "notes.md"  # type: ignore[operator]
        f.write_text("محتوى ملف عن وكلاء الأسطول وذاكرتهم.", encoding="utf-8")  # type: ignore[union-attr]
        r = index.ingest_file(str(f))
        assert r["doc_id"] == "notes.md" and r["slices"] == 1
        with pytest.raises(FileNotFoundError):
            index.ingest_file(tmp_path / "ghost.md")  # type: ignore[operator]


class TestRetrieve:
    def test_budget_stops_packing(self, index: OpsIndex) -> None:
        """التغليف يتوقف عند أول شريحة تتجاوز الميزانية — السقف قاسٍ."""
        index.ingest_text(("كلمات كثيرة " * 60).strip(), "big", acl="team:all")
        result = index.retrieve("كلمات", budget_tokens=10, acl="team:all")
        if result["slices"]:
            assert result["tokens_used"] <= 10

    def test_acl_wildcard_and_public(self, index: OpsIndex) -> None:
        """الصلاحيات: العام للجميع وteam:* يفتح الفريق فقط."""
        index.ingest_text("سر فريق الذكاء الاصطناعي", "sec", acl="team:ai")
        assert index.retrieve("سر فريق", acl="team:ai")["slices"]
        assert not index.retrieve("سر فريق", acl="team:other")["slices"]
        assert index.retrieve("سر فريق", acl="team:*")["slices"]

    def test_citations_match_slices(self, index: OpsIndex) -> None:
        """الاستشهادات معرّفات الشرائح المعادة — المرجع موثّق دائمًا."""
        index.ingest_text("مستند الاستشهاد عن الأدلة.", "cited", acl="team:all")
        result = index.retrieve("الاستشهاد", acl="team:all")
        assert result["citations"] == [s["id"] for s in result["slices"]]

    def test_cache_hit_and_invalidation(self, index: OpsIndex) -> None:
        """الذاكرة المؤقتة تعيد النتيجة وتُبطَل عند الإدخال الجديد."""
        index.ingest_text("نص للاستعلام المتكرر عن الوكلاء.", "c1", acl="team:all")
        r1 = index.retrieve("الوكلاء", acl="team:all")
        assert index.retrieve("الوكلاء", acl="team:all") == r1
        index.ingest_text("نص جديد كليًا عن الوكلاء المتقدمة.", "c2", acl="team:all")
        r2 = index.retrieve("الوكلاء", acl="team:all")
        assert r2["slices"] != r1["slices"] or r2["citations"] != r1["citations"]

    def test_invalid_budget_rejected(self, index: OpsIndex) -> None:
        """ميزانية أقل من 1 رفع — استرجاع بلا سقف مرفوض تصميمًا."""
        with pytest.raises(ValueError, match="الميزانية"):
            index.retrieve("سؤال", budget_tokens=0)


class TestPrune:
    def test_expired_slices_removed(self, index: OpsIndex) -> None:
        """الشرائح المنتهية تُحذف والحيّ يبقى — التقادم صامت ومخزّن."""
        index.ingest_text("مستند سريع الزوال.", "ttl-doc", acl="team:all",
                          ttl_days=1)
        # ارفع تاريخ الإنشاء يدويًا إلى ما قبل النافذة.
        old = "2020-01-01T00:00:00+00:00"
        index._store._conn.execute(
            "UPDATE slices SET created_at = ? WHERE doc_id = 'ttl-doc'", (old,)
        )
        index.ingest_text("مستند دائم الخدمة.", "perm-doc", acl="team:all")
        pruned = index.prune_expired()
        assert pruned == 1
        remaining = index.search("الزوال", top_k=10)
        assert all(h["doc_id"] != "ttl-doc" for h in remaining)
        assert any(h["doc_id"] == "perm-doc" for h in index.search("الخدمة", top_k=10))

    def test_invalid_created_at_ignored_by_prune(self, index: OpsIndex) -> None:
        """الطابع الفاسد يُتجاهل في التقادم لا يفجّر الدورة — صدق دائم."""
        index.ingest_text("طابع فاسد لكن شرائح حية.", "bad-ts", acl="team:all",
                          ttl_days=1)
        index._store._conn.execute(
            "UPDATE slices SET created_at = 'not-a-timestamp' WHERE doc_id='bad-ts'"
        )
        assert index.prune_expired() == 0
