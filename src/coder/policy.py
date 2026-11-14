"""Coder Risk Policy — سياسة المخاطر التي تُحدِّد متى يدخل المجلس.

المبدأ (بعد إصلاح M4): **المجلس سلطة ترقية لا سلطة إيقاف.** لا يتوقف أي عمل
بانتظار مجلس، ولا يُستشار المجلس في كل شيء — السياسة تصنّف المخاطر الفعلية
لكل خطوة من المسار والإجراء لا من وسم النموذج وحده، فلا يُستشار المجلس إلا
حيث الخطر حقيقي.

ومنذ v1.61.0 (خطة التناغم ب1.1 — ``docs/harmony-plan.md``): **المجلس
لا يُستشار استباقياً أصلاً** — الوضع المعيار الجديد ``escalate``: لا مداولة
إلا عند العجز (محاولتان فاشلتان) أو بطلب صريح، ودور المجلس الدائم مراقبة
وتقييم الوكلاء عبر ``src.council.monitor``. الأوضاع الأخرى تبقى متاحة
للأنظمة المقيدة: ``blocking`` قبل التنفيذ، ``async`` مداولة متوازية،
``off`` بلا استشارة.
"""

from __future__ import annotations

import fnmatch

from src.coder.plan import RepairPlan, Step

__all__ = ["RiskPolicy", "COUNCIL_MODES"]

#: أوضاع المجلس المعلنة:
#: * ``escalate`` (المعيار منذ v1.61.0): **لا مداولة استباقية** — التنفيذ يمضي
#:   دائماً في الصندوق المعزول، والخطة العالية الخطر الناجحة تبقى ``pending``
#:   حتى توقيع صريح؛ والمداولة الوحيدة تشتعل **عند العجز**: محاولتان فاشلتان
#:   في التشغيل نفسه — يُستشار المجلس مرة واحدة بسياق العجز ليحل لا ليوقف.
#: * ``async``   (القديم المُتاح): مداولة متوازية لكل خطة عالية — العمل لا يتوقف.
#: * ``blocking`` (الأقدم): لا تنفيذ قبل موافقة المجلس — للأنظمة المقيدة.
#: * ``off``      : لا استشارة إطلاقاً؛ الخطوة عالية الخطورة تبقى محتاجة توقيعاً.
COUNCIL_MODES = ("escalate", "async", "blocking", "off")

#: عدد المحاولات الفاشلة في التشغيل الواحد قبل تصعيد العجز إلى المجلس (ب1.2).
ESCALATE_AFTER_FAILURES = 2

#: مسارات آمنة بتصميمها: توثيق واختبارات وتغييرات معلنة غير مكوّنات إنتاج.
SAFE_PATTERNS: tuple[str, ...] = (
    "docs/*", "*.md", "*.rst", "*.txt",
    "tests/*", "test_*", "*_test.py", "conftest.py",
    "CHANGELOG*", "LICENSE*", ".gitignore",
)

#: مسارات محمية: أمان، بيانات اعتماد، نشر، وبنية CI — خطورة عالية دائماً.
PROTECTED_PATTERNS: tuple[str, ...] = (
    "*credential*", "*secret*", "*token*", "*.env*", "*.pem", "*.key",
    ".github/*", "deploy/*", "Dockerfile*", "docker-compose*",
    "*/auth/*", "*auth*", "*/security/*", "security/*",
    "*.lock", "pyproject.toml", "Makefile",
)


class RiskPolicy:
    """مُصنِّف المخاطر الفعلي — مصدر الحقيقة الوحيد لمطلب المجلس.

    قواعد التصنيف لكل خطوة، بالترتيب:

    1. حماية: مسار محمي أو إجراء حذف ⇒ ``high`` (أياً كان وسم النموذج).
    2. أمان: مسار آمن (توثيق/اختبارات) وغير محمي ⇒ ``low`` حتى لو وسَمَه
       النموذج عالياً — هذا ما يمنع تدخل المجلس في كل شيء.
    3. سائر الحالات: وسم النموذج كما هو.
    """

    def __init__(self, *, safe_patterns: tuple[str, ...] = SAFE_PATTERNS,
                 protected_patterns: tuple[str, ...] = PROTECTED_PATTERNS) -> None:
        self.safe_patterns = safe_patterns
        self.protected_patterns = protected_patterns

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _match(path: str, patterns: tuple[str, ...]) -> bool:
        """مطابقة مسار نمط fnmatch واحد أو أكثر (بغير حساسية حالة)."""
        lowered = path.lower().replace("\\", "/")
        return any(fnmatch.fnmatch(lowered, p.lower()) for p in patterns)

    def effective_risk(self, step: Step) -> str:
        """المخاطر الفعلية لخطوة واحدة وفق قواعد السياسة."""
        if step.action == "delete" or self._match(step.file, self.protected_patterns):
            return "high"
        if self._match(step.file, self.safe_patterns):
            return "low"
        return step.risk

    def high_risk_steps(self, plan: RepairPlan) -> list[str]:
        """مسارات الخطوات التي خرجت بمخاطر فعلية عالية."""
        return [step.file for step in plan.steps
                if self.effective_risk(step) == "high"]

    def needs_council(self, plan: RepairPlan) -> bool:
        """هل تُستشار المجلس لهذه الخطة؟ فقط لوجود خطوة خطورتها الفعلية عالية."""
        return bool(self.high_risk_steps(plan))