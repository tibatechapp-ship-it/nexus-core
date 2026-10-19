from typing import Dict, Type
from .base import BaseConnector
from .openai import OpenAIConnector
from .anthropic import AnthropicConnector
from .groq import GroqConnector
from .ollama import OllamaConnector
from .deepseek import DeepSeekConnector
from .gemini import GeminiConnector

PROVIDER_MAP: Dict[str, Type[BaseConnector]] = {
    "openai": OpenAIConnector,
    "anthropic": AnthropicConnector,
    "groq": GroqConnector,
    "ollama": OllamaConnector,
    "deepseek": DeepSeekConnector,
    "gemini": GeminiConnector,
}

def get_connector_class(provider_id: str) -> Type[BaseConnector]:
    cls = PROVIDER_MAP.get(provider_id.lower())
    if not cls:
        raise ValueError(f"Unsupported provider: {provider_id}")
    return cls

def list_providers() -> list[str]: return list(PROVIDER_MAP.keys())
