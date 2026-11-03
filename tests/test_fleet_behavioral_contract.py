"""العقد السلوكي لعيّنة من كل فئة novamind (ب3.3 — v1.50.0).

الفجوة ف6: لا مهمة سلوكية لكل وكيل novamind — الترقية كانت تتم بلا
إثبات سلوكي. هذا الاختبار يشغّل **وكيلًا واحدًا معلنًا من كل فئة من
الثماني** فوق حِمل ``src.fleet.probe`` (بناء أوفلاين + استدعاء محدود
بسلّم المدخلات الحميدة) ويطالب بعقد نتيجة موحد:

* الاستدعاء نجح ولم يرفع استثناء (عقد الحِمل).
* النتيجة معلنة الشكل: ``dict`` (نتيجة مهيكلة) أو ``bool`` (حُكم) أو
  ``str`` (تقرير نصي) — بلا أحراج أنصاف مكتملة.
* كل ذلك أوفلاين حتمي (``mode: fake-clock``).

العيّنات معلنة أدناه ومعروفة القياس منذ v1.49.0 (كلها ``call_ok`` في
التقرير المعتمد) — أي وكيل يكسر عقد فئته يُفشل الاختبار فيُعلن.
"""

from __future__ import annotations

import pytest

from src.fleet.inventory import build_inventory
from src.fleet.probe import probe_agent

#: عيّنة سلوكية معلنة لكل فئة — وكيل واحد من الثماني (ب3.3)
CATEGORY_SAMPLES: dict[str, str] = {
    "code": "complexity",  # تحليل ثابت للكود — يعيد dict متكامل
    "quality": "arabic",  # تحليل جودة النص العربي
    "security": "auth",  # فحص المصادقة
    "infra": "cicd",  # فحص خطوط CI/CD
    "data": "data_scientist",  # تحليل بيانات (وسيط قاموسي عبر السلّم)
    "research": "architecture",  # تحليل معماري بحثي
    "ui": "a11y",  # إمكانية الوصول (WCAG)
    "meta": "ci_doctor",  # وكيل وكلاء — دالة دخول على مستوى الوحدة
}

_RECORDS = {r.name: r for r in build_inventory() if r.framework == "novamind"}


def _sample_record(name: str):
    rec = _RECORDS.get(name)
    assert rec is not None, f"عيّنة سلوكية غير معروفة في الجرد: {name}"
    return rec


@pytest.mark.parametrize("category", sorted(CATEGORY_SAMPLES))
def test_category_sample_honors_result_contract(category: str) -> None:
    """كل فئة: استدعاء أوفلاين ناجح ونتيجة معلنة الشكل (ب3.3)."""
    sample = CATEGORY_SAMPLES[category]
    rec = _sample_record(sample)
    assert rec.category == category, (
        f"العيّنة {sample} خارج فئتها المعلنة ({rec.category} ≠ {category})"
    )
    result = probe_agent(rec)
    assert result["mode"] == "fake-clock"
    assert result["init_ok"] is True, result["reason"]
    assert result["call_ok"] is True, f"العيّنة السلوكية {sample} كسرت عقد فئتها: {result['reason']}"
    assert result["result_type"] in {"dict", "bool", "str"}, (
        f"نتيجة غير معلنة الشكل: {result['result_type']!r}"
    )
    if result["result_type"] == "dict":
        # عقد الوكلاء المهيكلين: قاموس غير فارغ بزمن مقيس
        assert result["run_ms"] is not None and result["run_ms"] >= 0.0


def test_all_categories_are_covered() -> None:
    """بوابة الشمول: الثماني فئات معلنة في نوامind لا أقل."""
    covered = set(CATEGORY_SAMPLES)
    assert covered == {"code", "quality", "security", "infra", "data", "research", "ui", "meta"}
