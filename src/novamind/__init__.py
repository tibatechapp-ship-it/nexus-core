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
