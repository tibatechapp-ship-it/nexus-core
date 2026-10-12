"""
Compatibility shim — use core.settings directly in new code.
"""
from novamind.core.settings import (
    settings,
    NOVAMIND_HOME,
    MEMORY_DIR,
    LOGS_DIR,
    WORKSPACE_DIR,
    VECTOR_STORE_DIR,
    KG_DIR,
    PROVIDERS_DIR,
    safe_mkdir,
)


def get_novamind_home():
    return NOVAMIND_HOME


def get_writable_dir(base, subdir):
    return safe_mkdir(base / subdir)


__all__ = [
    "settings", "NOVAMIND_HOME", "MEMORY_DIR", "LOGS_DIR",
    "WORKSPACE_DIR", "VECTOR_STORE_DIR", "KG_DIR", "PROVIDERS_DIR",
    "get_novamind_home", "get_writable_dir", "safe_mkdir",
]
