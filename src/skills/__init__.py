"""نظام المهارات (الطبقة 3 من تدريب الوكلاء).

* ``loader`` — قراءة ``SKILL.md`` من بذرة المستودع + تجاوز المستخدم.
* ``inject`` — حقن مهارات الوكيل (من بيانه) في تعليماته قبل المهمّة.

``api`` (FastAPI) **لا يُستورد هنا** — يبقى النظام قابلاً للاستيراد بلا FastAPI،
وتُركَّب الراوتات صراحةً عند وجودها.
"""

from __future__ import annotations

from .inject import (
    DEFAULT_LIMIT,
    agent_skill_names,
    inject_skills_into_prompt,
    skills_block,
)
from .loader import DEFAULT_SKILLS, SEED_DIR, SKILLS_DIR, Skill, SkillLoader

__all__ = [
    "DEFAULT_LIMIT",
    "DEFAULT_SKILLS",
    "SEED_DIR",
    "SKILLS_DIR",
    "Skill",
    "SkillLoader",
    "agent_skill_names",
    "inject_skills_into_prompt",
    "skills_block",
]
