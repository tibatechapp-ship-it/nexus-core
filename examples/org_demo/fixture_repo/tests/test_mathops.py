"""اختبارات أساس — الحالة الطبيعية فقط قبل المهمة."""
from calc.mathops import divide


def test_divide_normal():
    assert divide(10, 2) == 5
