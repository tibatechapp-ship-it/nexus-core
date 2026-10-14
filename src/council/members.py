"""أعضاء المجلس — 3 أدوار."""
from dataclasses import dataclass


@dataclass
class CouncilMember:
    name: str
    role: str
    system_prompt: str
    permissions: list
    max_output_length: int = 500


PROFILER = CouncilMember(
    name="profiler",
    role="المحلل المتشكك",
    system_prompt="حلل المخاطر في جملتين. ابدأ بـ 'خطر:'",
    permissions=["read_context", "analyze_risk"],
)

ANALYST = CouncilMember(
    name="analyst",
    role="المدافع",
    system_prompt="قدم المزايا في جملتين. ابدأ بـ 'آمن:'",
    permissions=["read_context", "analyze_benefits"],
)

CRITIC = CouncilMember(
    name="critic",
    role="الناقد",
    system_prompt="انقد الحجتين في جملتين. ابدأ بـ 'مقبول:' أو 'مرفوض:'",
    permissions=["read_context", "critique"],
)

JUDGE_CONFIG = {
    "name": "judge",
    "weights": {"profiler": 0.3, "analyst": 0.3, "critic": 0.4},
    "thresholds": {"approve": 0.7, "reject": 0.3},
}
