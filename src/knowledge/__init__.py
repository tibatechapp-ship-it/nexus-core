"""Knowledge Base — الطبقة المشتركة (الذاكرة الساخنة) لكل الوكلاء.

    from src.knowledge import KnowledgeBase, get_knowledge_base

    block = get_knowledge_base().for_agent("coder", "add a CLI flag")

الوثائق هي ملفات markdown، والمصدران بذرة المستودع ``<repo>/knowledge/``
وتجاوز المستخدم ``~/.config/nexus/knowledge/``.
"""

from __future__ import annotations

from .base import (
    DEFAULT_LIMIT,
    KB_DIR,
    SEED_DIR,
    KnowledgeBase,
    KnowledgeDoc,
    get_knowledge_base,
    normalize_token,
    parse_front_matter,
    reset_knowledge_base,
    tokenize,
)

__all__ = [
    "KnowledgeBase",
    "KnowledgeDoc",
    "KB_DIR",
    "SEED_DIR",
    "DEFAULT_LIMIT",
    "normalize_token",
    "tokenize",
    "parse_front_matter",
    "get_knowledge_base",
    "reset_knowledge_base",
]
