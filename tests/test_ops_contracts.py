"""اختبارات العقود الموحّدة — التحقق الصريح وآلة الحالات والتحويلات.

العقد بلا اختبار بلا عقد: كل تحقق في ``__post_init__`` يُختبَر بنص
الخطأ، وكل معرّف حتمي يُختبَر بالثبات، وكل تحويل dict يُختبَر
ذهابًا وإيابًا.
"""

from __future__ import annotations

import pytest

from src.ops.contracts import (
    ALLOWED_TRANSITIONS,
    Digest,
    GateResult,
    Signal,
    Ticket,
    Verdict,
    now_iso,
    stable_id,
)


class TestStableId:
    """المعرّف الحتمي — أساس إزالة التكرار والتخزين الإلزامي."""

    def test_deterministic_same_input(self) -> None:
        """نفس المدخلات يعطي نفس المعرّف في كل استدعاء."""
        assert stable_id("pypi", "https://x") == stable_id("pypi", "https://x")

    def test_differs_by_parts_and_separator(self) -> None:
        """الأجزاء تُفصل بفاصل داخلي — ('ab','c') لا يطابق ('a','bc')."""
        assert stable_id("ab", "c") != stable_id("a", "bc")

    def test_fixed_length_hex(self) -> None:
        """المعرّف 12 خانة سداسية عشرية — ثابت الشكل للعرض والتخزين."""
        value = stable_id("a")
        assert len(value) == 12
        assert all(ch in "0123456789abcdef" for ch in value)


class TestNowIso:
    def test_iso_format_utc(self) -> None:
        """الطابع الزمني ISO بنهاية UTC — عقود الزمن واحدة."""
        stamp = now_iso()
        assert stamp.endswith("+00:00") and "T" in stamp


class TestSignal:
    def test_valid_minimal_with_auto_id(self) -> None:
        """الإشارة الدنيا تعمل ومعرّفها يُشتق حتميًا من المصدر والرابط."""
        s = Signal(source="pypi", title="حزمة جديدة", url="https://pypi.org/x")
        assert s.id == stable_id("pypi", "https://pypi.org/x")
        assert s.created_at.endswith("+00:00")

    def test_round_trip_dict(self) -> None:
        """التحويل ذهابًا وإيابًا يحفظ الحقول كلها."""
        s = Signal(source="npm", title="t", url="https://npm/x", score=2.5,
                   tags=("a", "b"), raw_ref="row1", published_at="2026-11-14")
        assert Signal.from_dict(s.to_dict()) == s

    def test_from_dict_missing_optional_defaults(self) -> None:
        """المفاتيح الناقصة تعود لافتراضاتها — لا انفجار على JSON ناقص."""
        s = Signal.from_dict({"source": "g", "title": "t", "url": "u"})
        assert s.score == 0.0 and s.tags == () and s.id

    def test_invalid_rejected(self) -> None:
        """كل انتهاك يرفع رسالة عربية صريحة لا تخمينًا."""
        with pytest.raises(ValueError, match="source"):
            Signal(source="", title="t", url="u")
        with pytest.raises(ValueError, match="title"):
            Signal(source="s", title="  ", url="u")
        with pytest.raises(ValueError, match="url"):
            Signal(source="s", title="t", url="")
        with pytest.raises(ValueError, match="score"):
            Signal(source="s", title="t", url="u", score="not-number")  # type: ignore[arg-type]

    def test_score_coerced_to_float_and_tags_tuple(self) -> None:
        """الدرجة تُحوَّل إلى float والوسوم إلى tuple — التطبيع في البناء."""
        s = Signal(source="s", title="t", url="u", score=3, tags=["x"])  # type: ignore[arg-type]
        assert isinstance(s.score, float) and s.tags == ("x",)


class TestVerdict:
    def test_valid_defaults_inconclusive(self) -> None:
        """الافتراضي غير محسوم — الصدق الافتراضي مُثبت بالبناء نفسه."""
        v = Verdict(target="pkg@1", evidence=("دليل",))
        assert v.verdict == "inconclusive" and v.needs_ticket

    def test_requires_evidence(self) -> None:
        """حكم بلا أدلة مرفوض — require_evidence شرط عقد لا أداة."""
        with pytest.raises(ValueError, match="أدلة"):
            Verdict(target="pkg@1", evidence=())

    def test_confirmed_and_safe_no_ticket_for_safe(self) -> None:
        """المؤكَّد يفتح تذكرة والآمن لا يفتح — خريطة التذاكر معلنة."""
        assert Verdict(target="t", verdict="confirmed", evidence=("e",)).needs_ticket
        assert Verdict(target="t", verdict="inconclusive", evidence=("e",)).needs_ticket
        assert not Verdict(target="t", verdict="safe", evidence=("e",)).needs_ticket

    def test_invalid_verdict_and_confidence(self) -> None:
        """الحكم من الثوابت والثقة داخل [0,1] — خارجها رفع."""
        with pytest.raises(ValueError, match="verdict"):
            Verdict(target="t", verdict="maybe", evidence=("e",))
        with pytest.raises(ValueError, match="confidence"):
            Verdict(target="t", evidence=("e",), confidence=1.5)
        with pytest.raises(ValueError, match="confidence"):
            Verdict(target="t", evidence=("e",), confidence="high")  # type: ignore[arg-type]

    def test_round_trip(self) -> None:
        """التحويل ذهابًا وإيابًا يحفظ الأدلة والفحوص والتذكرة."""
        v = Verdict(target="t", verdict="confirmed", evidence=("e1", "e2"),
                    confidence=0.8, checks={"static_scan": "finding"},
                    ticket_id="T-1", id="abc")
        assert Verdict.from_dict(v.to_dict()) == v


class TestTicket:
    def test_branch_from_id(self) -> None:
        """الفرع يُشتق من المعرّف — t/<id> اسم معلن منذ البناء."""
        t = Ticket(origin="radar", title="مراجعة", id="T-2026-001")
        assert t.branch == "t/T-2026-001" and t.publish_allowed is False

    def test_invalid_origin_state_report(self) -> None:
        """المصدر والحالة من الثوابت والتقرير قاموس — خارجها رفع."""
        with pytest.raises(ValueError, match="origin"):
            Ticket(origin="nowhere", title="t")
        with pytest.raises(ValueError, match="state"):
            Ticket(origin="radar", title="t", state="floating")
        with pytest.raises(ValueError, match="report"):
            Ticket(origin="radar", title="t", report=["list"])  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="publish_allowed"):
            Ticket(origin="radar", title="t", publish_allowed="yes")  # type: ignore[arg-type]

    def test_round_trip(self) -> None:
        """التحويل ذهابًا وإيابًا يحفظ الحالة والتقرير وبوابة النشر."""
        t = Ticket(origin="webqa", title="t", state="reviewed", id="T-1",
                   report={"what": "x"}, publish_allowed=True)
        assert Ticket.from_dict(t.to_dict()) == t


class TestGateResult:
    def test_passing_gate_no_findings_ok(self) -> None:
        """بوابة ناجحة بلا نتائج مسموحة — الفشل وحده يتطلب أدلة."""
        g = GateResult(tool="webqa", target="dir")
        assert g.passed and g.findings == ()

    def test_failed_gate_requires_findings(self) -> None:
        """فشل بلا نتائج مرفوض — لا حكم سلبي بلا دليل."""
        with pytest.raises(ValueError, match="نتائج"):
            GateResult(tool="webqa", target="dir", passed=False)

    def test_blocking_and_passed_are_bools(self) -> None:
        """blocking و passed منطقيان صريحان — لا أعداد تخمينية."""
        with pytest.raises(ValueError, match="منطقيين"):
            GateResult(tool="w", target="t", blocking=1, passed=True)  # type: ignore[arg-type]

    def test_round_trip(self) -> None:
        """التحويل ذهابًا وإيابًا يحفظ النتائج والتذكرة المرتبطة."""
        g = GateResult(tool="webqa", target="dir", blocking=True, passed=False,
                       findings=({"check": "html_validate"},), ticket_id="T-2")
        assert GateResult.from_dict(g.to_dict()) == g


class TestDigest:
    def test_kinds_and_day_required(self) -> None:
        """نوع الملخص من الثوابت واليوم نص إلزامي — الملخص بلا يوم مرفوض."""
        d = Digest(kind="cycle", day="2026-11-14")
        assert d.id == stable_id("cycle", "2026-11-14")
        with pytest.raises(ValueError, match="kind"):
            Digest(kind="hourly", day="2026-11-14")
        with pytest.raises(ValueError, match="day"):
            Digest(kind="cycle", day=" ")
        with pytest.raises(ValueError, match="payload"):
            Digest(kind="cycle", day="d", payload=[])  # type: ignore[arg-type]

    def test_round_trip(self) -> None:
        """التحويل ذهابًا وإيابًا يحفظ الحمولة كما بُنيت."""
        d = Digest(kind="morning", day="2026-11-14", payload={"summary": "س"})
        assert Digest.from_dict(d.to_dict()) == d


class TestTransitions:
    def test_legal_chain(self) -> None:
        """السلسلة القانونية كاملة — open إلى merged عبر خمس خطوات."""
        chain = ["open", "branched", "executed", "reported", "reviewed", "merged"]
        for current, nxt in zip(chain, chain[1:]):
            assert nxt in ALLOWED_TRANSITIONS[current]

    def test_final_states_frozen(self) -> None:
        """الحالات النهائية لا انتقال منها — merged/closed طريق مسدود."""
        assert ALLOWED_TRANSITIONS["merged"] == frozenset()
        assert ALLOWED_TRANSITIONS["closed"] == frozenset()

    def test_closed_from_every_active_state(self) -> None:
        """الإغلاق متاح من كل حالة نشطة — مسار النهاية الآمنة مضمون."""
        for state, targets in ALLOWED_TRANSITIONS.items():
            if state not in {"merged", "closed"}:
                assert "closed" in targets
