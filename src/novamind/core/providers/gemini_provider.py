"""Gemini Provider — Google AI Studio (60K TPM per key)."""
from __future__ import annotations
import os
import json
import logging
import httpx

logger = logging.getLogger("GeminiProvider")


class GeminiProvider:
    """مزود Google Gemini (عبر AI Studio API)."""

    ENDPOINT_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.8-flash",
        priority: int = 2,
        account_id: str = "1",
    ):
        if not api_key:
            raise ValueError("GeminiProvider requires api_key")

        self.name = f"gemini-{account_id}"
        self.api_key = api_key
        self.model = model
        self.priority = priority
        self.account_id = account_id
        self.endpoint = (
            f"{self.ENDPOINT_BASE}/{model}:generateContent"
        )
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
        )

    async def close(self):
        await self._client.aclose()

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not prompt and not system_prompt:
            raise ValueError("prompt or system_prompt required")

        MAX_RETRIES = 3
        last_error = None

        for attempt in range(MAX_RETRIES):
            # ابْن payload
            contents = []
            if prompt:
                contents.append({
                    "role": "user",
                    "parts": [{"text": prompt}],
                })

            payload = {"contents": contents}
            if system_prompt:
                payload["systemInstruction"] = {
                    "parts": [{"text": system_prompt}],
                }

            headers = {"Content-Type": "application/json"}

            try:
                res = await self._client.post(
                    self.endpoint,
                    params={"key": self.api_key},
                    json=payload,
                    headers=headers,
                )

                # نجاح
                if res.status_code == 200:
                    data = res.json()
                    try:
                        text = data["candidates"][0]["content"]["parts"][0]["text"]
                    except (KeyError, IndexError) as e:
                        raise RuntimeError(
                            f"Gemini: unexpected response: {str(e)[:100]}"
                        )
                    if not text or not text.strip():
                        raise RuntimeError("Gemini returned empty content")
                    return text

                # 503 (overload) أو 429 (rate limit) → retry
                if res.status_code in (503, 429):
                    last_error = f"Gemini HTTP {res.status_code}"
                    if attempt < MAX_RETRIES - 1:
                        wait = 0.5 * (2 ** attempt)  # 0.5s, 1s, 2s
                        logger.warning(
                            f"{self.name} HTTP {res.status_code}, "
                            f"retry {attempt+1}/{MAX_RETRIES} after {wait}s"
                        )
                        import asyncio as _aio
                        await _aio.sleep(wait)
                        continue
                    # آخر محاولة — ارفع الخطأ
                    raise httpx.HTTPStatusError(
                        f"Gemini HTTP {res.status_code}: {res.text[:200]}",
                        request=res.request, response=res,
                    )

                # أي status آخر → ارفع فورًا بدون retry
                raise httpx.HTTPStatusError(
                    f"Gemini HTTP {res.status_code}: {res.text[:200]}",
                    request=res.request, response=res,
                )

            except (httpx.ConnectError, httpx.ReadTimeout) as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    wait = 0.5 * (2 ** attempt)
                    logger.warning(
                        f"{self.name} network error, "
                        f"retry {attempt+1}/{MAX_RETRIES} after {wait}s: {e}"
                    )
                    import asyncio as _aio
                    await _aio.sleep(wait)
                    continue
                raise

        raise RuntimeError(f"Gemini exhausted retries: {last_error}")
