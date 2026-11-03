"""GLM cloud connector (Z.AI API) plus the local-first failover wrapper.

مهمة M1.4: السحابة احتياط فقط — كل نداء يجرب المحلي أولاً، وعند فشله وحده
يمر عبر السحابة، ثم يعود تلقائيًا إلى المحلي في النداء التالي (بلا حالة).

Env (read lazily at call time, never at import — BYOK purity):
  GLM_CLOUD_BASE   API base (default https://api.z.ai/api/paas/v4); a value
                   already ending in /chat/completions is used verbatim.
  GLM_CLOUD_MODEL  cloud model id (default glm-5.3; e.g. glm-5.3-flash to
                   trade quality for cost on the fallback path).
  ZAI_API_KEY / ZAI_TOKEN  bearer token — REQUIRED on the cloud path.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

from .base import BaseConnector
from .glm_local import GlmLocalConnector


class GlmCloudConnector(BaseConnector):
    """Z.AI-hosted GLM over the platform's OpenAI-compatible cloud API."""

    BASE_URL = "https://api.z.ai/api/paas/v4/chat/completions"
    DEFAULT_MODEL = "glm-5.3"
    TEMPERATURE = 0.2
    MAX_TOKENS = 8192
    TIMEOUT_S = 120.0

    def default_model(self) -> str:
        return os.getenv("GLM_CLOUD_MODEL") or self.DEFAULT_MODEL

    def _endpoint(self) -> str:
        """Resolve the endpoint at call time; tolerate a full-endpoint override."""
        base = os.getenv("GLM_CLOUD_BASE", self.BASE_URL).rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"

    def _auth_header(self) -> Dict[str, str]:
        key = self.api_key or os.getenv("ZAI_API_KEY") or os.getenv("ZAI_TOKEN")
        return {"Authorization": f"Bearer {key}"} if key else {}

    async def generate(self, prompt: str, system_prompt: str = "") -> Dict[str, Any]:
        if not (self.api_key or os.getenv("ZAI_API_KEY") or os.getenv("ZAI_TOKEN")):
            return {"ok": False, "error": "Missing Z.AI API key"}
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


class GlmFailoverConnector(BaseConnector):
    """Local-first GLM access with automatic failover to the Z.AI cloud.

    Every call retries the local server first (zero egress cost); only when
    the local path fails does the request go to the cloud, and the next call
    starts from local again — recovery is implicit and stateless. The served
    path is reported both via ``last_backend`` and a ``failover: True`` flag
    on cloud-served replies so callers (and later, the trace log) can see it.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        local: Optional[BaseConnector] = None,
        cloud: Optional[BaseConnector] = None,
    ) -> None:
        super().__init__(api_key=api_key, model=model)
        self.local = local or GlmLocalConnector(api_key=api_key, model=model)
        self.cloud = cloud or GlmCloudConnector(api_key=api_key, model=model)
        self.last_backend = "local"

    def default_model(self) -> str:
        return GlmLocalConnector.DEFAULT_MODEL

    async def generate(self, prompt: str, system_prompt: str = "") -> Dict[str, Any]:
        local_res = await self.local.generate(prompt, system_prompt)
        if local_res.get("ok"):
            self.last_backend = "local"
            return local_res
        cloud_res = await self.cloud.generate(prompt, system_prompt)
        if cloud_res.get("ok"):
            self.last_backend = "cloud"
            return {**cloud_res, "failover": True}
        self.last_backend = "none"
        return {
            "ok": False,
            "error": f"local: {local_res.get('error', '')}; cloud: {cloud_res.get('error', '')}"[:200],
        }
