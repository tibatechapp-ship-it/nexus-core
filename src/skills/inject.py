"""حقن المهارات في تعليمات الوكيل **قبل** المهمّة (الطبقة 3 من التدريب).

``SkillLoader`` يعرف كيف يقرأ ملفات ``SKILL.md``، لكن لا شيء كان يضعها داخل
برومبت الوكيل. هذه الوحدة تسدّ الفجوة:

    تعليمات الوكيل + كتلة المهارات (مهارات الوكيل من بيانه) + المهمّة

مصدر **أيّ** مهارات يملكها وكيل = بيانه (``AgentManifest.skills``، الطبقة 1) —
فلا تتكرّر الحقيقة في مكانين. تُمرَّر ``manifest`` نفسها فتُقرأ مهاراتها مباشرة،
أو يُمرَّر الوكيل/اسمه فيُبحث عنه في البيان.

معياري فقط (stdlib) — لا FastAPI ولا أي إضافة، ولا يستورد ``src.agents``
(يبقى القارئ مفكوكاً عن طبقة الوكلاء).
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from .loader import SEED_DIR, Skill, SkillLoader

__all__ = [
    "DEFAULT_LIMIT",
    "agent_skill_names",
    "get_skill_loader",
    "inject_skills_into_prompt",
    "reset_skill_loader",
    "skills_block",
]

#: أقصى عدد مهارات تُحقن في برومبت واحد (البقية تُهمَل بصمت).
DEFAULT_LIMIT = 3

#: الحقول التي قد تحمل اسم الوكيل، مرتّبة بالأولوية.
_NAME_ATTRS = ("name", "id", "agent_id")

_LOADER: Optional[SkillLoader] = None


def get_skill_loader() -> SkillLoader:
    """المحمّل العملي الواحد: بذرة المستودع + تجاوز المستخدم (singleton)."""
    global _LOADER
    if _LOADER is None:
        _LOADER = SkillLoader(seed_dir=SEED_DIR)
    return _LOADER


def reset_skill_loader() -> None:
    """يُفرِغ المحمّل (للاختبارات — يقرأ القرص من جديد)."""
    global _LOADER
    _LOADER = None


def _agent_id(agent: Any) -> str:
    """معرّف الوكيل من نصّ/كائن وكيل/بيان (بأمان)."""
    if isinstance(agent, str):
        return agent.strip()
    for attr in _NAME_ATTRS:
        value = getattr(agent, attr, None)
        if isinstance(value, str) and value:
            return value
    return ""


def agent_skill_names(agent: Any) -> tuple[str, ...]:
    """أسماء مهارات الوكيل من بيانه — فارغة عند أي فشل (لا يرمي أبداً).

    ``agent`` إمّا بيان يحمل ``skills`` مباشرةً، أو وكيل/اسم يُبحث في البيان.
    """
    inline = getattr(agent, "skills", None)
    if isinstance(inline, (tuple, list)):
        return tuple(str(s) for s in inline if str(s).strip())
    ident = _agent_id(agent)
    if not ident:
        return ()
    try:
        from src.agents.manifest import get_manifest

        return tuple(get_manifest(ident).skills)
    except Exception:  # بيان غائب/معرّف مجهول ⇒ بلا مهارات
        return ()


def load_skills(
    names: Sequence[str], *, loader: Optional[SkillLoader] = None
) -> list[Skill]:
    """يحمّل المهارات الموجودة فعلاً من ``names`` (يتخطّى غير المعروف)."""
    base = loader if loader is not None else get_skill_loader()
    found: list[Skill] = []
    for name in names:
        skill = base.load(name)
        if skill is not None:
            found.append(skill)
    return found


def render_skills(skills: Sequence[Skill]) -> str:
    """يُصيغ المهارات ككتلة نصية جاهزة للحقن (نمط كتلة قاعدة المعرفة)."""
    if not skills:
        return ""
    names = ", ".join(skill.name for skill in skills)
    parts = [
        "### المهارات المُفعَّلة (Skills)",
        f"<!-- skills: {names} -->",
    ]
    for skill in skills:
        parts.append("")
        parts.append(f"#### {skill.description}  ·  {skill.name}")
        parts.append(skill.content)
    return "\n".join(parts)


def skills_block(
    agent: Any,
    *,
    loader: Optional[SkillLoader] = None,
    limit: int = DEFAULT_LIMIT,
) -> str:
    """كتلة مهارات الوكيل وحدها (بلا تعليمات ولا قسم مهمّة).

    تُستخدم حين تكون التعليمات جاهزة أصلاً فنضيف المهارات فقط.
    """
    names = agent_skill_names(agent)[: max(0, limit)]
    return render_skills(load_skills(names, loader=loader))


def inject_skills_into_prompt(
    instructions: str,
    agent: Any,
    *,
    loader: Optional[SkillLoader] = None,
    limit: int = DEFAULT_LIMIT,
) -> str:
    """يعيد ``instructions`` متبوعةً بكتلة مهارات الوكيل (أو كما هي لو لا مهارات)."""
    block = skills_block(agent, loader=loader, limit=limit)
    text = instructions.strip() if isinstance(instructions, str) else ""
    if not block:
        return text
    if not text:
        return block
    return f"{text}\n\n{block}"
