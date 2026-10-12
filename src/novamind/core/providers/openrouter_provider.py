"""OpenRouter Provider - بوابة لعشرات النماذج."""
import os
import httpx
import logging

logger = logging.getLogger("OpenRouterProvider")


class OpenRouterProvider:
    """OpenRouter - نماذج مجانية (Llama, Qwen, DeepSeek)."""
    
    ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
    
    def __init__(self, api_key: str, model: str = "google/gemma-4-26b-a4b-it:free",
                 priority: int = 1, account_id: str = "1"):
        if not api_key:
            raise ValueError("OpenRouterProvider requires api_key")
        self.name = f"openrouter-{account_id}"
        self.api_key = api_key
        self.model = model
        self.priority = priority
        self.account_id = account_id
        self.endpoint = os.getenv("OPENROUTER_ENDPOINT", self.ENDPOINT)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)
        )
    
    async def close(self):
        await self._client.aclose()
    
    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not prompt and not system_prompt:
            raise ValueError("prompt or system_prompt required")
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://novamind.local",
            "X-Title": "NovaMind",
        }
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if prompt:
            messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 2048,
        }
        
        res = await self._client.post(self.endpoint, json=payload, headers=headers)
        
        if res.status_code == 200:
            data = res.json()
            content = data["choices"][0]["message"]["content"]
            if not content or not content.strip():
                raise RuntimeError("OpenRouter returned empty content")
            return content
        
        raise httpx.HTTPStatusError(
            f"OpenRouter HTTP {res.status_code}: {res.text[:200]}",
            request=res.request, response=res,
        )
