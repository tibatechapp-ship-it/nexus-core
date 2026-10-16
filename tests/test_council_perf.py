"""حرس أداء للمجلس — معايير T5.3/T5.4 (§5 في تقرير v1.13.4).

القاعدة: معايير زمن المجلس تُقاس على **المسار الحتمي (offline)** —
`Council(router=None)` — لأن المسار الحيّ مربوط بالشبكة (نداء واحد
15–48 ثانية حسب المزوّد)، فترتيب زمنه يعتمد على الشبكة لا على الكود.
هذا الملف يثبّت المعيار على المسار الذي نملكه فعلًا، فيتحوّل من رقم في
تقرير إلى عقد يُكسر فورًا إن تدهور الأداء.

الميزانية: T5.3 = جولة واحدة < 2s، T5.4 = جولتان < 6s.
الهامش المقيس ~1000× (2–4ms فعليًا)، فالفشل هنا يعني تدهورًا حقيقيًا.
"""

from __future__ import annotations

import time

import pytest

from src.novamind.council import COUNCIL_MEMBERS, Council

# المعايير كما وردت في التقرير (ثوانٍ).
T53_ONE_ROUND = 2.0
T54_TWO_ROUNDS = 6.0


def _offline_council() -> Council:
    """مجلس بلا مزوّد ولا مخزن: مسار حتمي، بلا شبكة ولا قرص."""
    return Council(router=None, store=None)


@pytest.mark.parametrize(
    ("rounds", "budget"),
    [(1, T53_ONE_ROUND), (2, T54_TWO_ROUNDS)],
)
def test_offline_debate_within_budget(rounds: int, budget: float) -> None:
    """T5.3/T5.4: جلسة offline تُكمل داخل الميزانية الزمنية."""
    council = _offline_council()
    start = time.perf_counter()
    result = council.debate("هل نبني الميزة الآن؟", rounds=rounds)
    elapsed = time.perf_counter() - start

    assert result["offline"] is True
    assert result["verdict"]
    assert elapsed < budget, (
        f"offline debate ({rounds} round(s)) took {elapsed:.3f}s "
        f">= budget {budget}s"
    )


def test_offline_debate_scales_linearly() -> None:
    """3 جولات تبقى داخل ميزانية الجولتين — لا انفجار في التعقيد."""
    council = _offline_council()
    start = time.perf_counter()
    council.debate("موضوع", rounds=3)
    elapsed = time.perf_counter() - start

    assert elapsed < T54_TWO_ROUNDS


def test_offline_debate_covers_all_members() -> None:
    """كل عضو في COUNCIL_MEMBERS له نتيجة تأثير — والعدد عقد v1.13.3 = 6."""
    council = _offline_council()
    result = council.debate("موضوع", rounds=1)

    assert set(result["influence"]) == {m.id for m in COUNCIL_MEMBERS}
    assert len(COUNCIL_MEMBERS) == 6
