"""RBAC Permissions Matrix — مصفوفة الصلاحيات حسب الدور.

This is the SINGLE SOURCE OF TRUTH for permissions in NovaMind.
Any agent's permissions are derived from its role.

Usage:
    from novamind.security.permissions import (
        get_permissions, has_permission,
        ROLE_PERMISSIONS, ALL_PERMISSIONS
    )

    perms = get_permissions("coder")  # from role
    if has_permission("coder", "write_code"):
        ...
"""
from __future__ import annotations

from typing import Dict, List, Set


# ═══════════════════════════════════════════════════════════════
# ROLE → PERMISSIONS MATRIX
# ═══════════════════════════════════════════════════════════════

ROLE_PERMISSIONS: Dict[str, List[str]] = {
    # ─── Executive: تخطيط وقرارات ───
    "executive": [
        "plan",
        "approve",
        "delegate",
        "review",
        "read_all",
        "write_decisions",
        "override",
    ],

    # ─── Researcher: بحث وتحليل ───
    "researcher": [
        "read_all",
        "analyze",
        "document",
        "search",
        "gather_context",
    ],

    # ─── Engineer: بناء واختبار ───
    "engineer": [
        "read_code",
        "write_code",
        "edit_files",
        "run_tests",
        "run_commands",
        "commit",
        "install_deps",
        "read_all",
    ],

    # ─── Quality: مراجعة وتدقيق ───
    "quality": [
        "read_all",
        "review_code",
        "run_tests",
        "audit",
        "block_merge",
        "report_issues",
    ],

    # ─── Automation: مراقبة وتنفيذ ───
    "automation": [
        "monitor",
        "trigger",
        "schedule",
        "read_status",
        "execute_scheduled",
        "heal",
    ],

    # ─── Ops (جديد للـ maintenance_agent) ───
    "ops": [
        "read_all",
        "monitor",
        "diagnose",
        "apply_fix",
        "report_issues",
        "heal",
    ],
}


# ═══════════════════════════════════════════════════════════════
# AGENT → ROLE MAPPING
# ═══════════════════════════════════════════════════════════════
# كل وكيل يُعيَّن دوراً افتراضياً إذا لم يُحدَّد في registry.
# المفاتيح هنا تتجاوز الافتراضي.

AGENT_ROLE_OVERRIDES: Dict[str, str] = {
    # ─── Executive ───
    "chief_architect": "executive",
    "project_manager": "executive",
    "quality_guardian": "executive",

    # ─── Researcher ───
    "lead_researcher": "researcher",
    "analyzer": "researcher",
    "arabic_analyzer": "researcher",
    "multilang_analyzer": "researcher",
    "complexity_agent": "researcher",
    "evaluation_agent": "researcher",

    # ─── Quality ───
    "code_review_agent": "quality",
    "test_runner": "quality",
    "test_generator": "quality",
    "tester": "quality",
    "compliance_agent": "quality",
    "audit_agent": "quality",

    # ─── Automation ───
    "maintenance_agent": "ops",
    "monitoring_agent": "automation",
    "cleanup_agent": "automation",
    "cicd_agent": "automation",

    # ─── Engineer (default for most) ───
    "coder": "engineer",
    "fixer": "engineer",
    "multi_fixer": "engineer",
    "senior_engineer": "engineer",
    "junior_engineer": "engineer",
    "architect": "engineer",
    "refactor_agent": "engineer",
    "migration_agent": "engineer",
    "db_migration_agent": "engineer",

    # ─── Security (Executive + Engineer mix) ───
    "security_agent": "quality",
    "security_engineer": "quality",
    "secret_scanner": "quality",
    "secrets_agent": "quality",
    "injection_agent": "quality",
    "xss_agent": "quality",
    "crypto_agent": "quality",
    "auth_agent": "quality",
    "privacy_agent": "quality",

    # ─── DevOps ───
    "devops_engineer": "engineer",
    "docker_agent": "engineer",
    "k8s_agent": "engineer",
    "terraform_agent": "engineer",
    "nginx_agent": "engineer",

    # ─── Data ───
    "data_scientist": "researcher",
    "embedding_agent": "researcher",
    "indexing_agent": "researcher",
}


# ═══════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════

ALL_PERMISSIONS: Set[str] = {
    perm
    for perms in ROLE_PERMISSIONS.values()
    for perm in perms
}


def get_role_for_agent(agent_name: str, default: str = "engineer") -> str:
    """يُعيد الدور المُعيَّن لوكيل (أو الافتراضي)."""
    return AGENT_ROLE_OVERRIDES.get(agent_name, default)


def get_permissions(agent_name: str) -> List[str]:
    """يُعيد قائمة الصلاحيات لوكيل بناءً على دوره."""
    role = get_role_for_agent(agent_name)
    return list(ROLE_PERMISSIONS.get(role, []))


def get_permissions_by_role(role: str) -> List[str]:
    """يُعيد صلاحيات دور مباشرة."""
    return list(ROLE_PERMISSIONS.get(role, []))


def has_permission(agent_name: str, permission: str) -> bool:
    """يتحقق إن كان الوكيل يمتلك صلاحية معينة."""
    perms = get_permissions(agent_name)
    return permission in perms or "*" in perms


def has_any_permission(agent_name: str, permissions: List[str]) -> bool:
    """يتحقق إن كان الوكيل يمتلك أي من الصلاحيات."""
    perms = set(get_permissions(agent_name))
    return bool(perms & set(permissions))


def has_all_permissions(agent_name: str, permissions: List[str]) -> bool:
    """يتحقق إن كان الوكيل يمتلك كل الصلاحيات."""
    perms = set(get_permissions(agent_name))
    return set(permissions).issubset(perms)


def list_agents_by_role(role: str) -> List[str]:
    """يُعيد قائمة الوكلاء بدور معيّن."""
    return [agent for agent, r in AGENT_ROLE_OVERRIDES.items() if r == role]


def role_summary() -> Dict[str, int]:
    """ملخص: عدد الوكلاء لكل دور."""
    summary: Dict[str, int] = {}
    for role in AGENT_ROLE_OVERRIDES.values():
        summary[role] = summary.get(role, 0) + 1
    return summary


__all__ = [
    "ROLE_PERMISSIONS",
    "AGENT_ROLE_OVERRIDES",
    "ALL_PERMISSIONS",
    "get_role_for_agent",
    "get_permissions",
    "get_permissions_by_role",
    "has_permission",
    "has_any_permission",
    "has_all_permissions",
    "list_agents_by_role",
    "role_summary",
]
