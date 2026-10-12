"""Nova Guards — طبقة التحقق من المخرجات + RBAC bridge.

Bridges:
    - Local guards (code, schema, file, import, output)
    - Hallucination guard
    - RBAC permissions (from novamind.security.permissions)
"""
from novamind.factory.guards.base import Guard, GuardResult
from novamind.factory.guards.code_guard import CodeGuard
from novamind.factory.guards.schema_guard import SchemaGuard
from novamind.factory.guards.file_guard import FileGuard
from novamind.factory.guards.import_guard import ImportGuard
from novamind.factory.guards.output_guard import OutputGuard
from novamind.factory.guards.chain import GuardChain, build_default_chain
from novamind.factory.guards.hallucination_guard import (
    HallucinationGuard,
    add_hallucination_to_chain,
)

# ─── RBAC bridge (يحافظ على التوافق العكسي) ───
try:
    from novamind.factory.guards import (
        can_agent_use_tool,
        require_permission,
        get_agent_permissions,
        get_agent_role,
        PermissionDenied,
    )
except ImportError:
    # fallback بسيط
    def can_agent_use_tool(agent_name, tool): return True
    def require_permission(agent_name, tool): pass
    def get_agent_permissions(agent_name): return []
    def get_agent_role(agent_name): return "unknown"
    class PermissionDenied(Exception): pass

__all__ = [
    # existing
    "Guard", "GuardResult",
    "CodeGuard", "SchemaGuard", "FileGuard", "ImportGuard", "OutputGuard",
    "GuardChain", "build_default_chain",
    "HallucinationGuard", "add_hallucination_to_chain",
    # RBAC
    "can_agent_use_tool", "require_permission",
    "get_agent_permissions", "get_agent_role",
    "PermissionDenied",
]
