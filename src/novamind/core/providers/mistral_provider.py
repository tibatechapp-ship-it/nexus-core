"""Mistral Provider — واجهة متوافقة مع OpenAI Chat Completions."""
from __future__ import annotations
import logging
import httpx

logger = logging.getLogger("MistralProvider")


class MistralProvider:
    """مزود Mistral AI عبر endpoint متوافق مع OpenAI."""

    BASE_URL = "https://api.mistral.ai/v1/chat/completions"

    def __init__(
        self,
        api_key: str,
        model: str = "mistral-small-latest",
        priority: int = 2,
        account_id: str = "1",
    ):
        if not api_key:
            raise ValueError("MistralProvider requires api_key")

        self.name = f"mistral-{account_id}"
        self.api_key = api_key
        self.model = model
        self.priority = priority
        self.account_id = account_id
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)
        )

    async def close(self):
        await self._client.aclose()

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not prompt and not system_prompt:
            raise ValueError("prompt or system_prompt required")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if prompt:
            messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        res = await self._client.post(self.BASE_URL, json=payload, headers=headers)

        if res.status_code == 200:
            data = res.json()
            try:
                text = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError) as e:
                raise RuntimeError(f"Mistral: unexpected response: {str(e)[:100]}")
            if not text or not text.strip():
                raise RuntimeError("Mistral returned empty content")
            return text

        error_detail = res.text[:200]
        raise httpx.HTTPStatusError(
            f"Mistral HTTP {res.status_code}: {error_detail}",
            request=res.request, response=res,
        )
