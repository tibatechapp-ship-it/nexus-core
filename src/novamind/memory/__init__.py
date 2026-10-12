"""NovaMind Memory Module."""
import sys
from pathlib import Path

# أضف /public إلى المسار
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# حاول استيراد memory من nova.memory (النسخة الجديدة)
try:
    from novamind.memory.memory import memory
    __all__ = ["memory"]
except ImportError:
    # إذا فشل، اجعله None (placeholder)
    memory = None
    __all__ = []
