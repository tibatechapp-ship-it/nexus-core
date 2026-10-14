"""NovaMind — Multi-Agent Orchestration Platform."""

__version__ = "3.4.0"

# ═══ Compatibility shims (must load early) ═══
# These allow `import config` and `import memory` (without novamind prefix)
# to work as legacy imports.

import sys as _sys

def _install_shim(name: str, module_path: str):
    """Install a sys.modules shim for legacy imports."""
    try:
        mod = __import__(module_path, fromlist=[name])
        if name not in _sys.modules:
            _sys.modules[name] = mod
    except ImportError:
        pass

# Install shims on package import
_install_shim("config", "novamind.cli.entries.config")
_install_shim("memory", "novamind.memory")


# ═══════════════════════════════════════════════════════════════
# Extended shims — for legacy imports in agents
# ═══════════════════════════════════════════════════════════════

def _install_extended_shims():
    """يُثبّت shims لـ: config, memory, agents.X, novamind.base, novamind.sandbox."""
    import sys as _s
    from importlib import import_module as _imp

    # 1. config → novamind.cli.entries.config (يحتوي EXECUTE_TIMEOUT و WORKSPACE_DIR)
    try:
        if "config" not in _s.modules:
            _s.modules["config"] = _imp("novamind.cli.entries.config")
    except ImportError:
        pass

    # 2. memory → novamind.memory (يحتوي memory object)
    try:
        if "memory" not in _s.modules:
            _s.modules["memory"] = _imp("novamind.memory")
    except ImportError:
        pass

    # 3. agents → novamind.agents (لكي يعمل agents.multilang_analyzer)
    try:
        if "agents" not in _s.modules:
            _s.modules["agents"] = _imp("novamind.agents")
    except ImportError:
        pass

_install_extended_shims()
