"""Memory shim."""
import sys
from novamind import memory as _memory_module
sys.modules["memory"] = _memory_module
memory = getattr(_memory_module, "memory", None)
