"""حقن المعرفة في تعليمات الوكيل **قبل** المهمّة (الطبقة 2 من التدريب).

هذه هي الحلقة التي كانت ناقصة: ``KnowledgeBase`` تعرف المشروع، لكن لا شيء
كان يضع ذلك داخل البرومبت. ``inject_into_prompt`` يبني البرومبت النهائي:

    تعليمات الوكيل (system_prompt)
    + كتلة المعرفة (nexus-core + conventions + وثيقة فئة الوكيل + الأصلة بالمهمّة)
    + المهمّة

كل وحدة معيارية فقط (stdlib) — لا FastAPI ولا أي إضافة.
"""

from __future__ import annotations

from typing import Any, Optional

from .base import DEFAULT_LIMIT, KnowledgeBase, get_knowledge_base

__all__ = [
    "inject_into_prompt",
    "knowledge_block",
    "agent_name",
    "agent_prompt",
    "agent_category",
]

#: الحقول التي قد تحمل اسم الوكيل، مرتّبة بالأولوية.
_NAME_ATTRS = ("name", "id", "agent_id")

#: الحقول التي قد تحمل نصّ تعليمات الوكيل، مرتّبة بالأولوية.
_PROMPT_ATTRS = ("system_prompt", "identity", "prompt")


def agent_name(agent: Any) -> str:
    """اسم الوكيل من نصّ أو كائن وكيل أو سجل (manifest).

    يقبل ``"coder"`` أو ``CoderAgent(...)`` أو ``AgentManifest`` — كلّها
    تحمل الاسم في حقل مختلف، فنقرأه بأمان.
    """
    if isinstance(agent, str):
        return agent.strip()
    for attr in _NAME_ATTRS:
        value = getattr(agent, attr, None)
        if isinstance(value, str) and value:
            return value
    return type(agent).__name__.lower()


def agent_prompt(agent: Any) -> str:
    """نصّ تعليمات الوكيل (قد يكون فارغاً — مثلاً حين يُمرَّر الاسم وحده)."""
    if isinstance(agent, str):
        return ""
    for attr in _PROMPT_ATTRS:
        value = getattr(agent, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def agent_category(agent: Any) -> str:
    """فئة الوكيل = مجموعته (``core``/``planning``/``quality``/``ops``)."""
    group = getattr(agent, "group", "")
    return group.strip() if isinstance(group, str) else ""


def knowledge_block(
    agent: Any,
    task: str = "",
    *,
    kb: Optional[KnowledgeBase] = None,
    limit: int = DEFAULT_LIMIT,
) -> str:
    """كتلة المعرفة وحدها لوكيل ومهمّة (بلا تعليمات ولا قسم مهمّة).

    تُستخدم حين تكون التعليمات جاهزة أصلاً (مثلًا برومبت البنّاء) فنضيف
    المعرفة فقط دون تكرار نصّ المهمّة.
    """
    base = kb if kb is not None else get_knowledge_base()
    return base.for_agent(agent_name(agent), task, limit, agent_category(agent))


def inject_into_prompt(
    agent: Any,
    task: str,
    *,
    kb: Optional[KnowledgeBase] = None,
    limit: int = DEFAULT_LIMIT,
    include_task: bool = True,
    instructions: Optional[str] = None,
) -> str:
    """يبني البرومبت النهائي: **تعليمات الوكيل + المعرفة + المهمّة**.

    - ``instructions`` يتجاوز نص تعليمات الوكيل (يفيد حين تكون التعليمات جاهزة
      في موضع الاستدعاء، أو لوكيل بلا ``system_prompt``).
    - ``include_task=False`` يُسقط قسم المهمّة (يُستعمل حين تكون المهمّة هي دور
      المستخدم نفسه في الدردشة، فنريد الاستدلال بها للاختيار لا نسخَها).
    - ``kb`` قابل للحقن (اختبارات/استنساخ) — الافتراضي النسخة العملية الواحدة.
    الأقسام الفارغة تُحذَف، فلا تظهر عناوين بلا محتوى.
    """
    base = kb if kb is not None else get_knowledge_base()
    block = base.for_agent(
        agent_name(agent), task, limit, agent_category(agent)
    )
    heading = instructions if instructions is not None else agent_prompt(agent)
    parts = []
    if heading and heading.strip():
        parts.append(heading.strip())
    if block:
        parts.append(block)
    if include_task and task.strip():
        parts.append(f"### المهمّة\n{task.strip()}")
    return "\n\n".join(parts)
