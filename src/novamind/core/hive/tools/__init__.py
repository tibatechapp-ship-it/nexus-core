"""hive.tools — try real registry first, fallback to stub."""
try:
    from novamind.security.registry import get_registry as _real
    def get_registry():
        return _real()
except ImportError:
    def get_registry():
        return {}

def execute_tool_calls(*args, **kwargs):
    return []
