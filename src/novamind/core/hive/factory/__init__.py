"""Hive Factory package."""

import sys
from pathlib import Path
import importlib

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# registry
# ب2.3 (v1.49.1): الالتقاط يشمل AttributeError — قد يُحلّ الاسم
# "registry" إلى حزمة مختلفة عند تلوث sys.path (معلن: التدهور الرشيق
# نفسه، بلا انفجار وقت الاستيراد).
try:
    _registry_module = importlib.import_module("registry")
    registry = _registry_module.registry
    AgentRegistry = _registry_module.AgentRegistry
    AgentSpec = _registry_module.AgentSpec
except (ImportError, AttributeError):
    registry = None
    AgentRegistry = None
    AgentSpec = None

# الوحدات الفرعية (يحتاجها pytest)
try:
    executor = importlib.import_module("hive.factory.executor")
except ImportError as e:
    print(f"⚠️ executor import failed: {e}")
    executor = None

try:
    llm_wrapper = importlib.import_module("hive.factory.llm_wrapper")
except ImportError as e:
    print(f"⚠️ llm_wrapper import failed: {e}")
    llm_wrapper = None

__all__ = ["registry", "AgentRegistry", "AgentSpec", "executor", "llm_wrapper"]
