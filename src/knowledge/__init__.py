"""Knowledge Base — الطبقة المشتركة (الذاكرة الساخنة) لكل الوكلاء.

    from src.knowledge import KnowledgeBase, get_knowledge_base, inject_into_prompt

    block = get_knowledge_base().for_agent("coder", "add a CLI flag")
    prompt = inject_into_prompt(agent, "add a CLI flag")   # تعليمات + معرفة + مهمّة

الوثائق هي ملفات markdown، والمصدران بذرة المستودع ``<repo>/knowledge/``
وتجاوز المستخدم ``~/.config/nexus/knowledge/``.

ملاحظة: ``api`` **لا** يُستورد هنا — يبقى سطح المعرفة قابلاً للاستيراد بلا
FastAPI مثبّتاً (``from src.knowledge.api import register`` عند الحاجة فقط).
"""

from __future__ import annotations

from .base import (
    DEFAULT_LIMIT,
    KB_DIR,
    SEED_DIR,
    UNIVERSAL_DOCS,
    KnowledgeBase,
    KnowledgeDoc,
    get_knowledge_base,
    normalize_token,
    parse_front_matter,
    reset_knowledge_base,
    tokenize,
)
from .inject import (
    agent_category,
    agent_name,
    agent_prompt,
    inject_into_prompt,
    knowledge_block,
)

__all__ = [
    "KnowledgeBase",
    "KnowledgeDoc",
    "KB_DIR",
    "SEED_DIR",
    "DEFAULT_LIMIT",
    "UNIVERSAL_DOCS",
    "normalize_token",
    "tokenize",
    "parse_front_matter",
    "get_knowledge_base",
    "reset_knowledge_base",
    "inject_into_prompt",
    "knowledge_block",
    "agent_name",
    "agent_prompt",
    "agent_category",
]
