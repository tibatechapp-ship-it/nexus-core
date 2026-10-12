"""NovaMind Factory — مصانع التنفيذ والبناء.

يوفر هذا الـ package واجهات عليا للمصنع الرئيسي.
"""
from __future__ import annotations

# ═══ Agent Factory ═══
try:
    from novamind.agents.factory import (
        factory,
        AgentFactory,
    )
except ImportError:
    factory = None
    AgentFactory = None

# ═══ Executor — الأسماء الحقيقية ═══
try:
    from novamind.factory.executor import (
        execute_agent_sync,
        build_prompt,
        parse_output,
        pick_llm_for,
    )
except ImportError:
    execute_agent_sync = None
    build_prompt = None
    parse_output = None
    pick_llm_for = None

# ═══ Pipeline — الأسماء الحقيقية ═══
try:
    from novamind.factory.pipeline import (
        PipelineContext,
        run_pipeline_sync,
        list_pipelines,
        format_result,
    )
except ImportError:
    PipelineContext = None
    run_pipeline_sync = None
    list_pipelines = None
    format_result = None

# ═══ LLM Wrapper ═══
try:
    from novamind.factory.llm_wrapper import (
        make_llm_call,
        is_llm_available,
        list_providers,
        get_router,
    )
except ImportError:
    make_llm_call = None
    is_llm_available = None
    list_providers = None
    get_router = None

# ═══ Rate Limiter ═══
try:
    from novamind.factory.rate_limiter import get_limiter
except ImportError:
    get_limiter = None



# ═══ Secure Pipeline ═══
try:
    from novamind.factory.secure_pipeline import (
        SecurityPipeline,
        get_secure_pipeline,
        execute_secure,
    )
except ImportError:
    SecurityPipeline = None
    get_secure_pipeline = None
    execute_secure = None

__all__ = [
    # Security Pipeline
    "SecurityPipeline", "get_secure_pipeline", "execute_secure",
    # Agent Factory
    "factory",
    "AgentFactory",
    # Executor
    "execute_agent_sync",
    "build_prompt",
    "parse_output",
    "pick_llm_for",
    # Pipeline
    "PipelineContext",
    "run_pipeline_sync",
    "list_pipelines",
    "format_result",
    # LLM Wrapper
    "make_llm_call",
    "is_llm_available",
    "list_providers",
    "get_router",
    # Rate Limiter
    "get_limiter",
]
