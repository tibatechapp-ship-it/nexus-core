"""GLM local connector — self-hosted GLM weights behind an OpenAI-compatible server.

عقد BYOK الموحد: نفس واجهة ``generate()`` لكل الموصلات، والقراءة من البيئة
عند النداء لا عند الاستيراد. الافتراضي: خادم vLLM محلي يخدم GLM-5.3.

Env (read lazily at call time, never at import — BYOK purity):
  GLM_LOCAL_URL            full chat-completions endpoint (default: local vLLM :8000).
  GLM_MODEL                model id served by the endpoint (default: zai-org/GLM-5.3).
  ZAI_API_KEY / ZAI_TOKEN  bearer token (a bare vLLM server ignores it, so a
                           missing key is NOT an error here, unlike the cloud).
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

from .base import BaseConnector


class GlmLocalConnector(BaseConnector):
    """Local GLM backend (vLLM / SGLang / any OpenAI-compatible server)."""

    BASE_URL = "http://127.0.0.1:8000/v1/chat/completions"
    DEFAULT_MODEL = "zai-org/GLM-5.3"
    TEMPERATURE = 0.2
    MAX_TOKENS = 8192
    TIMEOUT_S = 180.0

    def default_model(self) -> str:
        # Runtime env read (construction time), never at import — BYOK purity.
        return os.getenv("GLM_MODEL") or self.DEFAULT_MODEL

    def _endpoint(self) -> str:
        """Resolve the endpoint at call time (no env read at import)."""
        return os.getenv("GLM_LOCAL_URL", self.BASE_URL)

    def _auth_header(self) -> Dict[str, str]:
        """Bearer header only when a key exists; a bare local server needs none."""
        key = self.api_key or os.getenv("ZAI_API_KEY") or os.getenv("ZAI_TOKEN")
        return {"Authorization": f"Bearer {key}"} if key else {}

    async def generate(self, prompt: str, system_prompt: str = "") -> Dict[str, Any]:
        messages = [{"role": "system", "content": system_prompt}] if system_prompt else []
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.TEMPERATURE,
            "max_tokens": self.MAX_TOKENS,
        }
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT_S) as client:
                r = await client.post(self._endpoint(), json=payload, headers=self._auth_header())
                r.raise_for_status()
                return {"ok": True, "reply": r.json()["choices"][0]["message"]["content"]}
        except Exception as e:  # noqa: BLE001 — the BYOK contract returns errors as data
            return {"ok": False, "error": str(e)[:200]}
