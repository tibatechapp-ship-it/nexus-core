"""BYOK layer — turn a per-request user config into a concrete LLM connector.

WHY this file exists: ``/api/agent/start`` accepts a ``user_config`` dict
(``hyper_app/routers/agent.py``) so a caller can pick provider/model/key per
request instead of a hardcoded global. This factory is the only place that
turns that dict into a connector instance.

Design rules (from the Day-1 spec):
- No network / clock / FS at import time. The factory reads ``api_key`` and
  ``model`` from the *request* dict, never from env at module level, so BYOK
  tests stay order-independent.
- ``connectors/ollama.py`` itself reads ``OLLAMA_HOST`` in its class body —
  that is env-only (no side effects that gate behaviour) and is the
  documented host override, so we leave it alone.
- An unknown provider raises ``ValueError`` (from ``registry.get_connector_class``)
  — callers decide whether to catch it; ``safe_execute``-style swallowing is
  the caller's job, not the factory's.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from connectors.registry import get_connector_class

DEFAULT_PROVIDER = "ollama"
DEFAULT_USER_CONFIG: Dict[str, Any] = {"provider": DEFAULT_PROVIDER}


def create_llm_client_from_request(
    user_config: Optional[Dict[str, Any]] = None,
) -> Any:
    """Build a connector instance from a per-request config.

    ``user_config`` keys:
      - ``provider`` (str): one of ``registry.PROVIDER_MAP`` (default ``ollama``).
      - ``api_key`` (str, optional): passed straight to the connector.
      - ``model`` (str, optional): overrides the provider's default model.

    Returns:
      A ``BaseConnector`` subclass instance, ready for ``await generate(...)``.

    Raises:
      ValueError: if ``provider`` is not registered (surfaced from the registry).
    """
    cfg = dict(user_config) if user_config else dict(DEFAULT_USER_CONFIG)
    provider = str(cfg.get("provider", DEFAULT_PROVIDER)).lower()
    api_key: Optional[str] = cfg.get("api_key")
    model: Optional[str] = cfg.get("model")

    connector_cls = get_connector_class(provider)
    return connector_cls(api_key=api_key, model=model)
