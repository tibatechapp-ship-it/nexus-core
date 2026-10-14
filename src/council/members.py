"""أعضاء المجلس — 4 أدوار متخصصة."""
from dataclasses import dataclass


@dataclass
class CouncilMember:
    name: str
    role: str
    system_prompt: str
    permissions: list
    max_output_length: int = 2000


PROFILER = CouncilMember(
    name="profiler",
    role="المحلل المتشكك",
    system_prompt="""أنت المحلل المتشكك في المجلس.
مهمتك: البحث عن كل سبب لعدم الثقة في الطلب.
- ابحث عن المخاطر الخفية.
- لا تقبل أي افتراض دون دليل.
- اذكر 3 مخاوف على الأقل.
- استخدم كلمة "خطر" عند اكتشاف مخاوف.""",
    permissions=["read_context", "analyze_risk"],
)

ANALYST = CouncilMember(
    name="analyst",
    role="المدافع المحلل",
    system_prompt="""أنت المحلل المدافع في المجلس.
مهمتك: البحث عن كل سبب لبناء حالة إيجابية.
- ابحث عن السياق المفقود.
- ابحث عن عوامل التخفيف.
- قدّم حجة منطقية.
- استخدم كلمة "آمن" عند الثقة.""",
    permissions=["read_context", "analyze_benefits"],
)

CRITIC = CouncilMember(
    name="critic",
    role="الناقد البناء",
    system_prompt="""أنت الناقد البناء في المجلس.
مهمتك: نقد الحجج المقدمة من المحلل والمدافع.
- ابحث عن الثغرات المنطقية.
- اقترح سيناريوهات فشل.
- كن صريحاً ومباشراً.
- استخدم "مرفوض" أو "مقبول" عند الحكم.""",
    permissions=["read_context", "critique"],
)

JUDGE_CONFIG = {
    "name": "judge",
    "weights": {"profiler": 0.3, "analyst": 0.3, "critic": 0.4},
    "thresholds": {"approve": 0.7, "reject": 0.3},
}
