"""AgentRecord — السجل الموحد لكل وكيل في الأسطول.

حقل واحد بلا إطارات: سواء جاء الوكيل من سجل novamind (``nova.yaml``) أو من
الإطار الأساسي (``src.agents.AGENT_CLASSES``) أو من وحدات الجذر القديمة،
فيمثّله نفس السجل، وهذا ما يجعل الجرد والقياس والترتيب ممكنين فوق ~150
وكيلاً بلا تفرّع حسب المصدر.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

__all__ = ["AgentRecord", "FRAMEWORKS"]

#: الإطارات المعروفة — قائمة مغلقة عمداً: أي إطار جديد يضاف هنا مع مكتشفه.
FRAMEWORKS = ("novamind", "core", "legacy")

#: حالات المطابقة الممكنة لكل وكيل (فحص conformance).
STATUSES = ("healthy", "degraded", "broken")


@dataclass(frozen=True)
class AgentRecord:
    """هوية وكيل واحد كما يراها الأسطول — بلا سلوك، بلا LLM.

    السجل متجمد (frozen) عمداً: الجرد لقطة معلنة لا حاوية قابلة للتعديل
    من الشارد، وأي تحديث يعني بناء سجل جديد بقرار صريح.
    """

    #: الاسم القانوني داخل إطاره.
    name: str
    #: الإطار المالك — أحد ``FRAMEWORKS``.
    framework: str
    #: مسار الوحدة النسبي لجذر المستودع (معلوماتي للبشر).
    source: str
    #: وحدة الاستيراد القابلة للاستدعاء عبر importlib (فارغة إن لم يوجد).
    module: str = ""
    #: رمز نقطة الدخول داخل الوحدة (صنف عادةً).
    symbol: str = ""
    #: الدور التشغيلي: tool | manager | service.
    role: str = "tool"
    #: الفئة الوظيفية: code | quality | security | infra | data | research | ui | meta.
    category: str = "meta"
    #: حرجية الخدمة: core | standard | optional.
    criticality: str = "standard"
    #: وصف قصير كما ورد في مصدر الحقيقة.
    description: str = ""
    #: دالة الدخول المعلنة (novamind فقط) — للتوثيق لا للتنفيذ.
    main_function: str = ""

    def to_json(self) -> dict:
        """إسقاط JSON خالص — كل الحقول، بلا حالات داخلية."""
        return asdict(self)
