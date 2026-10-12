"""
Secret Masking Utility
======================
Provides safe display of secrets in logs, error messages, and UIs.

Usage:
    from novamind.security.masking import mask_secret
    logger.info("Using key: %s", mask_secret(os.environ["GEMINI_API_KEY"]))
    # Output: Using key: EXAM...7QFA (masked, length=39)

Rules:
    - Never print raw secrets to stdout/stderr/logs
    - Never include secrets in exception messages
    - Always mask before display
"""

from __future__ import annotations

import os
import re
from typing import Optional


# Patterns for known API key formats
SECRET_PATTERNS = [
    # Google/Gemini: AIza... (39 chars)
    (re.compile(r"AIza[0-9A-Za-z_-]{35}"), "GEMINI_KEY"),
    # OpenAI: sk-... (48+ chars)
    (re.compile(r"sk-[0-9A-Za-z]{20,}"), "OPENAI_KEY"),
    # Groq: gsk_... 
    (re.compile(r"gsk_[0-9A-Za-z]{20,}"), "GROQ_KEY"),
    # Anthropic: sk-ant-...
    (re.compile(r"sk-ant-[0-9A-Za-z_-]{20,}"), "ANTHROPIC_KEY"),
    # OpenRouter: sk-or-...
    (re.compile(r"sk-or-[0-9A-Za-z_-]{20,}"), "OPENROUTER_KEY"),
    # Mistral
    (re.compile(r"[0-9A-Za-z]{32}"), "MISTRAL_KEY"),
    # Generic JWT
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "JWT"),
]


def mask_secret(value: Optional[str], show_chars: int = 4) -> str:
    """
    Mask a secret string, showing only first/last N characters.
    
    Args:
        value: The secret string (may be None or empty)
        show_chars: How many chars to show at each end
    
    Returns:
        Masked string like "AIza...7QFA" or "(empty)" or "(none)"
    
    Examples:
        >>> mask_secret("EXAMPLE_TOKEN")
        'AIza...4567'
        >>> mask_secret("")
        '(empty)'
        >>> mask_secret(None)
        '(none)'
    """
    if value is None:
        return "(none)"
    if not value:
        return "(empty)"
    if len(value) <= show_chars * 2:
        return "***" + str(len(value))
    return f"{value[:show_chars]}...{value[-show_chars:]}"


def mask_env_var(name: str) -> str:
    """
    Get an environment variable and return it masked.
    
    Args:
        name: Environment variable name
    
    Returns:
        Masked value or "(not set)"
    """
    value = os.environ.get(name)
    if value is None:
        return "(not set)"
    return mask_secret(value)


def sanitize_text(text: str) -> str:
    """
    Remove any secret-like patterns from arbitrary text.
    
    Use this before logging external data, error messages, or
    when you cannot be sure if a string contains a secret.
    
    Args:
        text: Arbitrary text that might contain secrets
    
    Returns:
        Text with secrets replaced by masked versions
    
    Examples:
        >>> sanitize_text("Failed with key AIzaSyABC...XYZ12345")
        'Failed with key AIza...2345'
    """
    if not isinstance(text, str):
        return str(text)
    
    for pattern, _name in SECRET_PATTERNS:
        text = pattern.sub(lambda m: mask_secret(m.group(0)), text)
    
    return text


def safe_dict(d: dict, secret_keys: Optional[list] = None) -> dict:
    """
    Return a copy of dict with known secret keys masked.
    
    Args:
        d: Dictionary possibly containing secrets
        secret_keys: List of keys to mask. If None, uses defaults.
    
    Returns:
        New dict with secret values masked
    """
    if secret_keys is None:
        secret_keys = [
            "api_key", "apikey", "key", "token", "secret",
            "password", "passwd", "pwd", "auth", "bearer",
            "gemini_api_key", "openai_api_key", "groq_api_key",
            "anthropic_api_key", "mistral_api_key",
            "openrouter_api_key", "glm_api_key", "zai_api_key",
        ]
    
    result = {}
    for k, v in d.items():
        if k.lower() in secret_keys:
            result[k] = mask_secret(str(v)) if v else v
        elif isinstance(v, dict):
            result[k] = safe_dict(v, secret_keys)
        else:
            result[k] = v
    
    return result


# Convenience alias
m = mask_secret


__all__ = [
    "mask_secret",
    "mask_env_var",
    "sanitize_text",
    "safe_dict",
    "m",
]
