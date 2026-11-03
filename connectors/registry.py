from typing import Dict, Type
from .base import BaseConnector
from .openai import OpenAIConnector
from .anthropic import AnthropicConnector
from .groq import GroqConnector
from .ollama import OllamaConnector
from .deepseek import DeepSeekConnector
from .gemini import GeminiConnector
from .glm_local import GlmLocalConnector
from .glm_cloud import GlmCloudConnector, GlmFailoverConnector

PROVIDER_MAP: Dict[str, Type[BaseConnector]] = {
    "openai": OpenAIConnector,
    "anthropic": AnthropicConnector,
    "groq": GroqConnector,
    "ollama": OllamaConnector,
    "deepseek": DeepSeekConnector,
    "gemini": GeminiConnector,
    # GLM (Z.AI) family — self-hosted weights, cloud fallback, and the
    # local-first failover wrapper (90-day plan, tasks M1.3 / M1.4).
    "glm-local": GlmLocalConnector,
    "glm-cloud": GlmCloudConnector,
    "glm": GlmFailoverConnector,
}

def get_connector_class(provider_id: str) -> Type[BaseConnector]:
    cls = PROVIDER_MAP.get(provider_id.lower())
    if not cls:
        raise ValueError(f"Unsupported provider: {provider_id}")
    return cls

def list_providers() -> list[str]: return list(PROVIDER_MAP.keys())
