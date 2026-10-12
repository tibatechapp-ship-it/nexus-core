"""Aliases: core -> nova.core, agents -> nova.agents."""
import sys
import importlib

ALIASES = [
    ("core", "nova.core"),
    ("core.security", "nova.core.security"),
    ("core.security.security_kernel_v3", "nova.core.security.security_kernel_v3"),
    ("core.llm_router", "nova.core.llm_router"),
    ("core.rag", "nova.core.rag"),
    ("core.rag.knowledge_graph", "nova.core.rag.knowledge_graph"),
    ("core.rag.vector_store", "nova.core.rag.vector_store"),
    ("hive.analytics", "nova.analytics"),
    ("hive.analytics.cost_tracker", "nova.analytics.cost_tracker"),
    ("hive.analytics.eval_tracker", "nova.analytics.eval_tracker"),
]

loaded = 0
for alias, target in ALIASES:
    try:
        mod = importlib.import_module(target)
        sys.modules[alias] = mod
        loaded += 1
    except ImportError:
        pass

try:
    import nova.agents
    sys.modules['agents'] = nova.agents
except ImportError:
    pass

print(f"_aliases.py: {loaded}/{len(ALIASES)} loaded")
