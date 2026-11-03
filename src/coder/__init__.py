"""Self-coding engine (90-day plan, phase 2) — five-stage loop over platform parts.

طبقة محرك البرمجة فوق منصة nexus-core: تحليل → اكتشاف → مخطط معلن → تنفيذ
معزول → بوابة جودة مستقلة. لا ملف يُعدَّل قبل RepairPlan صالح، وكل مرحلة
تُسجَّل في سجل الأثر المعياري للمنصة.
"""

from __future__ import annotations

from src.coder.analyzer import ModuleInfo, analyze_repo
from src.coder.plan import RepairPlan, Step, plan_from_json, validate

__all__ = ["ModuleInfo", "RepairPlan", "Step", "analyze_repo", "plan_from_json", "validate"]
