"""
Agent Alias — يحوّل أسماء الوكلاء القديمة → الجديدة.

Pipeline يستخدم أسماء قديمة، Registry يستخدم أسماء جديدة.
هذا الملف يربط بينهما.
"""

from __future__ import annotations
import logging

logger = logging.getLogger("novamind.adapters.agent_alias")


# ═══════════════════════════════════════════════════════════════
# Aliases — القديم → الجديد
# ═══════════════════════════════════════════════════════════════

AGENT_ALIASES = {
    # Code
    "code_review": "code_review_agent",
    "coder": "coder",
    "debug_agent": "fixer",
    "lint_agent": "analyzer",
    "type_agent": "analyzer",
    "test_generator": "test_generator",
    "test_runner": "test_runner",

    # Security
    "security": "security_agent",

    # Infra
    "docker": "docker_agent",
    "deploy_agent": "devops_engineer",
    "monitor_agent": "monitoring_agent",

    # Docs
    "docs_writer": "technical_writer",

    # Planning
    "task_planner": "architect",

    # Analysis
    "analyzer": "analyzer",
    "fixer": "fixer",
}


def resolve_agent(name: str) -> str:
    """
    يحوّل اسم الوكيل من pipeline → registry.

    Args:
        name: اسم الوكيل من pipeline

    Returns:
        اسم الوكيل الصحيح في registry
    """
    resolved = AGENT_ALIASES.get(name, name)
    if resolved != name:
        logger.debug(f"🔄 Alias: {name} → {resolved}")
    return resolved


def is_known(name: str) -> bool:
    """يتحقق إن كان الاسم معروفاً (قديم أو جديد)."""
    return name in AGENT_ALIASES


__all__ = ["AGENT_ALIASES", "resolve_agent", "is_known"]
