# هذا الملف يحتوي على مزود Groq للاستدلال الفائق السرعة
"""
Groq Provider - استدلال فائق السرعة.

المسؤولية:
- إدارة الاتصال بواجهة Groq API.
- تنفيذ طلبات الاستدلال (Inference) بشكل غير متزامن (Async).
- معالجة الأخطاء ومراقبة حدود المعدل (Rate Limits).
"""
import os
import json
import httpx
import asyncio
import logging
from typing import Optional

logger = logging.getLogger("GroqProvider")


class GroqProvider:
    """Groq API - Llama 3.3 70B بأسرع استدلال."""
    
    ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
    
    def __init__(self, api_key: str, model: str = "openai/gpt-oss-20b",
                 priority: int = 1):
        if not api_key:
            raise ValueError("GroqProvider requires api_key")
        self.name = f"groq-{model.split('-')[0]}"
        self.api_key = api_key
        self.model = model
        self.priority = priority
        self.endpoint = os.getenv("GROQ_ENDPOINT", self.ENDPOINT)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)
        )
    
    async def close(self):
        await self._client.aclose()
    
    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not prompt and not system_prompt:
            raise ValueError("prompt or system_prompt required")
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
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
                raise RuntimeError("Groq returned empty content")
            return content
        
        if res.status_code == 429:
            raise httpx.HTTPStatusError(
                f"Groq rate limit: {res.text[:200]}",
                request=res.request, response=res,
            )
        
        raise httpx.HTTPStatusError(
            f"Groq HTTP {res.status_code}: {res.text[:200]}",
            request=res.request, response=res,
        )
