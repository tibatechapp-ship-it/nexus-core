"""OllamaBackend — LLM backend يستخدم Ollama Cloud مباشرة.

Compat with the LLMBackend protocol (generate(messages) -> str).
يدوّر المفاتيح تلقائياً عند rate limits أو نفاد quota.

Usage:
    from src.core.ollama_backend import OllamaBackend
    from nexus_core import Agent
    
    backend = OllamaBackend()
    agent = Agent.load("analyst")
    result = agent.run("حلل مشروع wifi-chat")
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from src.core.types import Message

# ─── URL safety: only allow http/https (blocks file://, ftp://, etc.) ───
def _safe_urlopen(req: Any, *, timeout: float) -> Any:
    """Open a URL request, rejecting anything but http:// or https://."""
    import urllib.request as _urllib
    url = req.full_url if hasattr(req, "full_url") else str(req)
    if not (url.startswith("http://") or url.startswith("https://")):
        raise PermissionError(f"unsafe URL scheme (only http/https allowed): {url[:60]}")
    return _urllib.urlopen(req, timeout=timeout)

__all__ = ["OllamaBackend", "OllamaError"]

DEFAULT_BASE_URL = "https://ollama.com/v1"
DEFAULT_MODEL = "gemma4:31b"

# نماذج مجانية مُختبرة (بالأولوية)
FREE_MODELS = [
    # ⚡ سريعة جداً
    "nemotron-3-nano:30b",
    "gpt-oss:20b",
    # ⚖️ متوازنة
    "gemma4:31b",
    "gpt-oss:120b",
    "nemotron-3-super",
    # 🏆 قوية (للمهام الصعبة)
    "nemotron-3-ultra",
]

class OllamaError(RuntimeError):
    """فشل الاتصال بـ Ollama Cloud."""

class OllamaBackend:
    """LLMBackend يستخدم Ollama Cloud مع تدوير المفاتيح.
    
    - يحمّل المفاتيح من ~/.config/zyvo/keys/
    - يدوّر بينها عند الفشل
    - يدوّر بين النماذج عند فشل النموذج
    """
    
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        keys: Sequence[str] | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.keys = list(keys) if keys else self._load_keys()
        
        if not self.keys:
            raise OllamaError(
                "لا مفاتيح Ollama! أضف مفتاحاً في ~/.config/zyvo/keys/"
            )
        
        self._key_idx = 0
        self._model_idx = 0
        self.models = self._dedupe([model] + FREE_MODELS)
    
    @staticmethod
    def _load_keys() -> list[str]:
        """يحمّل كل المفاتيح الصالحة من مجلد active-2."""
        keys_dir = Path.home() / ".config" / "zyvo" / "keys"
        keys: list[str] = []
        
        # ═══ المصدر الأساسي: active-2 (المفاتيح النظيفة) ═══
        active2 = keys_dir / "active-2"
        if active2.exists():
            for kf in sorted(active2.glob("*.key")):
                try:
                    k = kf.read_text().strip()
                    if k and 50 <= len(k) <= 60 and k not in keys:
                        keys.append(k)
                except Exception:
                    continue
        
        # ═══ Fallback: متغيرات البيئة ═══
        env_key = os.environ.get("OLLAMA_API_KEY", "").strip()
        if env_key and env_key not in keys:
            keys.append(env_key)
        
        return keys
    
    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        """يحذف المكرر مع الحفاظ على الترتيب."""
        return list(dict.fromkeys(items))
    
    def _call(
        self,
        key: str,
        model: str,
        messages: Sequence[Message],
        max_tokens: int = 2000,
    ) -> str:
        """استدعاء Ollama API — يرفع OllamaError عند الفشل."""
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": getattr(m, "role", None) or (
                        m["role"] if isinstance(m, dict) else "user"
                    ),
                    "content": getattr(m, "content", None) or (
                        m["content"] if isinstance(m, dict) else str(m)
                    ),
                }
                for m in messages
            ],
            "max_tokens": max_tokens,
        }
        
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        
        try:
            with _safe_urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8")[:200]
            except Exception:
                pass
            raise OllamaError(f"HTTP {e.code}: {err_body}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise OllamaError(f"Network error: {e}") from e
        
        # استخرج النص
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise OllamaError(f"Unexpected response: {str(data)[:200]}") from e
    
    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
        max_tokens: int = 2000,
    ) -> str:
        """يولّد رداً مع تدوير المفاتيح والنماذج.
        
        Compat with LLMBackend protocol.
        """
        models_to_try = [model] if model else self.models
        last_error: Exception | None = None
        attempts = 0
        total_attempts = len(self.keys) * len(models_to_try)
        
        while attempts < total_attempts:
            key = self.keys[self._key_idx % len(self.keys)]
            self._key_idx += 1
            
            m = models_to_try[self._model_idx % len(models_to_try)]
            self._model_idx += 1
            
            attempts += 1
            
            try:
                return self._call(key, m, messages, max_tokens=max_tokens)
            except OllamaError as e:
                last_error = e
                err_lower = str(e).lower()
                # إذا كان rate limit → جرّب المفتاح التالي
                if "rate" in err_lower or "quota" in err_lower or "429" in err_lower:
                    continue
                # إذا كان النموذج غير متاح → جرّب النموذج التالي
                if "model" in err_lower or "404" in err_lower:
                    continue
                # خطأ آخر → نستمر
                continue
        
        raise OllamaError(
            f"فشلت كل المحاولات ({attempts}) — آخر خطأ: {last_error}"
        )
