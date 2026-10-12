


import os
import json
import asyncio
import logging
import httpx

logger = logging.getLogger("GLMProvider")


class GLMProvider:
    """مزود GLM-4-Flash السحابي (Zhipu AI)"""

    RETRY_DELAYS = (2.0, 5.0, 10.0)  # للـ 429/5xx

    def __init__(self, api_key: str, priority: int = 2):
        if not api_key:
            raise ValueError("GLMProvider يتطلب api_key")
        self.name = "glm-4.7-flash"
        self.api_key = api_key
        self.priority = priority
        self.endpoint = os.getenv(
            "GLM_ENDPOINT",
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        )
        self.model_chain = [
            os.getenv("GLM_MODEL") or "glm-4.7-flash",
            "glm-4.7-flash",
            "glm-4.6",
            "glm-4.5-air",
            "glm-4-plus",
        ]
        self.model = self.model_chain[0]
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)
        )

    async def close(self):
        await self._client.aclose()

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not prompt and not system_prompt:
            raise ValueError("يجب تقديم prompt أو system_prompt")

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

        last_error = None
        for attempt, delay in enumerate((0.0,) + self.RETRY_DELAYS):
            if delay:
                await asyncio.sleep(delay)
            try:
                res = await self._client.post(
                    self.endpoint, json=payload, headers=headers
                )
            except httpx.RequestError as e:
                last_error = e
                logger.warning(f"GLM شبكة (محاولة {attempt+1}): {e}")
                continue

            # نجاح
            if res.status_code == 200:
                return self._parse_response(res)

            # 429 (rate limit) أو 5xx → إعادة محاولة
            if res.status_code == 429 or 500 <= res.status_code < 600:
                last_error = httpx.HTTPStatusError(
                    f"HTTP {res.status_code}",
                    request=res.request,
                    response=res,
                )
                logger.warning(
                    f"GLM HTTP {res.status_code} (محاولة {attempt+1}): "
                    f"{res.text[:200]}"
                )
                continue

            # 401/403/404/400 → لا فائدة من إعادة المحاولة
            raise httpx.HTTPStatusError(
                f"GLM HTTP {res.status_code}: {res.text[:200]}",
                request=res.request,
                response=res,
            )

        # استُنفدت كل المحاولات
        raise RuntimeError(f"GLM فشل بعد {len(self.RETRY_DELAYS)+1} محاولات: {last_error}")

    @staticmethod
    def _parse_response(res: httpx.Response) -> str:
        try:
            data = res.json()
        except json.JSONDecodeError:
            raise RuntimeError(f"GLM رد ليس JSON: {res.text[:200]}")

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"GLM بنية رد غير متوقعة: {data}") from e

        if not content or not content.strip():
            raise RuntimeError("GLM أرجع محتوى فارغاً")
        return content
