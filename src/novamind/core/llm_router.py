"""
LLM Router - Unified interface for multiple providers
- Supports Gemini, Qwen, DeepSeek, OpenAI, Ollama
- Automatic fallback on errors
- Per-provider statistics
- Task-based routing (fast vs smart)
"""
import os
import time
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass

logger = logging.getLogger("llm_router")

# ─── Error Memory integration (v1.13.1.1) ───
try:
    from novamind.error_memory import get_error_memory
    HAS_ERROR_MEMORY = True
except ImportError:
    HAS_ERROR_MEMORY = False
    def get_error_memory():
        return None



@dataclass
class ProviderConfig:
    name: str
    api_key: str
    base_url: str
    models: Dict[str, str]
    priority: int = 100
    enabled: bool = True
    calls: int = 0
    failures: int = 0
    last_error: str = ""
    last_call_at: float = 0.0


class MockProvider:
    """Mock LLM provider for CI/testing — no network, deterministic."""
    name = "mock"
    api_key = "mock"
    base_url = ""
    models = {"fast": "mock", "smart": "mock"}
    priority = 999
    enabled = True
    calls = 0
    failures = 0
    last_error = ""
    last_call_at = 0.0

    
    def _get_ordered_candidates(self, role="fast", provider_override=None):
        import collections
        if provider_override:
            return [p for p in self.providers if p.name == provider_override and p.enabled]
        if not hasattr(self, "_rr_counters"):
            self._rr_counters = collections.defaultdict(int)
        unique = {}
        for p in self.providers:
            if p.enabled and p.name not in unique:
                unique[p.name] = p
        by_prio = collections.defaultdict(list)
        for p in unique.values():
            if p.models.get(role) or p.models.get("fast"):
                by_prio[p.priority].append(p)
        ordered = []
        for prio in sorted(by_prio.keys()):
            group = by_prio[prio]
            if len(group) > 1:
                idx = self._rr_counters[prio] % len(group)
                ordered.extend(group[idx:] + group[:idx])
                self._rr_counters[prio] = (self._rr_counters[prio] + 1) % len(group)
            else:
                ordered.extend(group)
        return ordered

    def generate(self, prompt, system="", **kwargs):
        return {
            "ok": True,
            "text": '{"verdict": "ok", "issues": [], "summary": "mock"}',
            "provider": "mock",
            "model": "mock",
            "elapsed": 0.0,
        }


class LLMRouter:
    def __init__(self):

        # --- Z.ai GLM Auto-Registration ---
        import os
        from pathlib import Path
        env_f = Path(".env")
        e_vars = {}
        if env_f.exists():
            for l in env_f.read_text().splitlines():
                if "=" in l and not l.strip().startswith("#"):
                    k, v = l.strip().split("=", 1)
                    e_vars[k.strip()] = v.strip().strip("'").strip('"')
        self.providers: List[ProviderConfig] = []
        self._clients: Dict[str, Any] = {}
        self._cooldowns: Dict[str, float] = {}  # provider -> cooldown_until
        self._load_from_env()

    def _load_from_env(self):
        """تحميل كل المزودين من البيئة — 60 مزود كامل."""
        env_path = Path(os.environ.get("NOVAMIND_HOME", "/public")) / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").split("\n"):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

        # 1. GEMINI — 21 مفتاح
        gemini_keys = []
        main = os.environ.get("GEMINI_API_KEY", "").strip()
        if main and main != "ضع_مفتاحك_هنا" and len(main) > 20:
            gemini_keys.append(("gemini", main))
        for i in range(1, 21):
            k = os.environ.get(f"GEMINI_API_KEY_{i}", "").strip()
            if k and k != "ضع_مفتاحك_هنا" and len(k) > 20:
                gemini_keys.append((f"gemini_{i}", k))
        for idx, (name, key) in enumerate(gemini_keys, 1):
            self.providers.append(ProviderConfig(
                name=name,
                api_key=key,
                base_url="https://generativelanguage.googleapis.com",
                models={
                    "fast":  "gemini-flash-latest",
                    "smart": "gemini-pro-latest",
                },
                priority=10 + idx,
            ))
        # تعطيل المفاتيح المعطوبة تلقائياً (503 من Google)
        broken_gemini_ids = {8, 13, 15, 16, 17, 19}
        for p in self.providers:
            if p.name.startswith("gemini_"):
                try:
                    idx = int(p.name.replace("gemini_", ""))
                    if idx in broken_gemini_ids:
                        p.enabled = False
                except ValueError:
                    pass
        logger.info(f"Gemini: {len(gemini_keys)} keys loaded ({len(broken_gemini_ids)} disabled)")

        # 2. GROQ — 20 مفتاح
        groq_keys = []
        for i in range(1, 21):
            k = os.environ.get(f"GROQ_API_KEY_{i}", "").strip()
            if k and len(k) > 20:
                groq_keys.append((f"groq_{i:02d}", k))
        for idx, (name, key) in enumerate(groq_keys, 1):
            self.providers.append(ProviderConfig(
                name=name,
                api_key=key,
                base_url="https://api.groq.com/openai/v1",
                models={
                    "fast":  "qwen/qwen3.8-27b",
                    "smart": "openai/gpt-oss-120b",
                },
                priority=2 + idx,
            ))
        logger.info(f"Groq: {len(groq_keys)} keys loaded")

        # 3. ZAI / GLM — 13 مفاتيح
        for i in range(1, 14):
            glm_key = os.environ.get(f"ZAI_API_KEY_{i}", "").strip()
            if glm_key and len(glm_key) > 10:
                self.providers.append(ProviderConfig(
                    name=f"zai_glm_{i}",
                    api_key=glm_key,
                    base_url="https://api.z.ai/api/paas/v4",
                    models={"fast": "glm-4.5-flash", "smart": "glm-4.5-flash"},
                    priority=1 + i,
                ))
        logger.info("ZAI/GLM loaded")

        # 4. OPENROUTER — 5 مفاتيح
        for i in range(1, 6):
            or_key = os.environ.get(f"OPENROUTER_API_KEY_{i}", "").strip()
            if or_key and len(or_key) > 20:
                self.providers.append(ProviderConfig(
                    name=f"openrouter{i}",
                    api_key=or_key,
                    base_url="https://openrouter.ai/api/v1",
                    models={
                        "fast":  "nvidia/nemotron-3.5-lightning:free",
                        "smart": "nvidia/nemotron-3-super-120b-a12b:free",
                    },
                    priority=6 + i,
                ))
        logger.info("OpenRouter loaded")

        # 5. MISTRAL — 9 مفاتيح
        mistral_count = 0
        for i in range(1, 10):
            mistral_key = os.environ.get(f"MISTRAL_API_KEY_{i}", "").strip()
            if mistral_key and len(mistral_key) > 20:
                self.providers.append(ProviderConfig(
                    name=f"mistral_{i}",
                    api_key=mistral_key,
                    base_url="https://api.mistral.ai/v1",
                    models={
                        "fast":  "ministral-3b-latest",
                        "smart": "mistral-small-latest",
                    },
                    priority=70 + i,
                ))
                mistral_count += 1
        logger.info(f"Mistral: {mistral_count} keys loaded")

        # 6. OLLAMA
        ollama_host = os.environ.get("OLLAMA_HOST", "").strip()
        if ollama_host:
            self.providers.append(ProviderConfig(
                name="ollama",
                api_key="ollama",
                base_url=ollama_host + "/v1",
                models={"fast": "llama3.2", "smart": "llama3.2"},
                priority=90,
            ))

        self.providers.sort(key=lambda p: p.priority)

        if not self.providers:
            logger.warning("No LLM providers configured — using MockProvider")
            self.providers.append(MockProvider())

        logger.info("loaded " + str(len(self.providers)) + " providers")

    def _get_client(self, provider: ProviderConfig):
        if provider.name in self._clients:
            return self._clients[provider.name]

        if provider.name == "gemini":
            from google import genai
            client = genai.Client(api_key=provider.api_key)
        else:
            from openai import OpenAI
            client = OpenAI(api_key=provider.api_key, base_url=provider.base_url)

        self._clients[provider.name] = client
        return client

    def _call_gemini(self, provider, model, prompt, system, temperature, max_tokens):
        client = self._get_client(provider)
        from google.genai import types

        config_kwargs = {"temperature": temperature}
        if system:
            config_kwargs["system_instruction"] = system
        if max_tokens:
            config_kwargs["max_output_tokens"] = max_tokens

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        return response.text or ""

    def _call_openai_compatible(self, provider, model, prompt, system, temperature, max_tokens):
        client = self._get_client(provider)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs = {"model": model, "messages": messages, "temperature": temperature}
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        response = client.chat.completions.create(**kwargs)

        # استخراج content النظيف — نتجنب reasoning_content قدر الإمكان
        # لكن إذا كان content فارغاً والنموذج reasoning، نستخدم reasoning_content
        text = ""
        reasoning = ""
        if hasattr(response, "model_dump"):
            try:
                data = response.model_dump()
                msg = data.get("choices", [{}])[0].get("message", {})
                text = msg.get("content") or ""
                reasoning = msg.get("reasoning_content") or ""
            except Exception:
                pass

        # fallback عبر الـ attributes
        if not text:
            try:
                text = getattr(response.choices[0].message, "content", None) or ""
                reasoning = reasoning or getattr(response.choices[0].message, "reasoning_content", None) or ""
            except Exception:
                pass

        # إذا كان content فارغاً، استخدم reasoning_content كحل أخير
        if not text and reasoning:
            text = reasoning

        return text
    def _get_ordered_candidates(self, role="fast", provider_override=None):
        import collections
        if provider_override:
            return [p for p in self.providers if p.name == provider_override and p.enabled]
        if not hasattr(self, "_rr_counters"):
            self._rr_counters = collections.defaultdict(int)
        unique = {}
        for p in self.providers:
            if p.enabled and p.name not in unique:
                unique[p.name] = p
        by_prio = collections.defaultdict(list)
        for p in unique.values():
            if p.models.get(role) or p.models.get("fast"):
                by_prio[p.priority].append(p)
        ordered = []
        for prio in sorted(by_prio.keys()):
            group = by_prio[prio]
            if len(group) > 1:
                idx = self._rr_counters[prio] % len(group)
                ordered.extend(group[idx:] + group[:idx])
                self._rr_counters[prio] = (self._rr_counters[prio] + 1) % len(group)
            else:
                ordered.extend(group)
        return ordered

    def generate(self, prompt, system="", role="fast", temperature=0.2,
                 max_tokens=None, provider=None, allow_fallback=True):
        candidates = self._get_ordered_candidates(role=role, provider_override=provider)

        if provider:
            candidates = [p for p in candidates if p.name == provider]
            if not candidates:
                return {"ok": False, "text": "", "provider": "", "model": "",
                        "error": "provider not found: " + provider, "elapsed": 0.0}

        if not allow_fallback:
            candidates = candidates[:1]

        last_error = ""

        for p in candidates:
            if not p.enabled:
                continue

            model = p.models.get(role) or p.models.get("fast")
            if not model:
                continue

            start = time.time()
            try:
                if p.name == "gemini":
                    text = self._call_gemini(p, model, prompt, system, temperature, max_tokens)
                else:
                    text = self._call_openai_compatible(p, model, prompt, system, temperature, max_tokens)

                elapsed = time.time() - start
                p.calls += 1
                p.last_call_at = time.time()

                return {"ok": True, "text": text, "provider": p.name,
                        "model": model, "error": "", "elapsed": round(elapsed, 2)}

            except Exception as e:
                elapsed = time.time() - start
                p.calls += 1
                p.failures += 1
                p.last_error = str(e)[:200]
                last_error = p.name + ": " + str(e)[:200]

                # 🆕 error_memory (v1.13.1.1)
                if HAS_ERROR_MEMORY:
                    try:
                        _mem = get_error_memory()
                        if _mem:
                            _mem.log(
                                error_type=type(e).__name__,
                                context=f"provider={p.name}",
                                error_message=str(e),
                                role=role,
                                provider=p.name,
                            )
                    except Exception:
                        pass
                logger.warning("provider " + p.name + " failed: " + str(e)[:120])

        return {"ok": False, "text": "", "provider": "", "model": "",
                "error": last_error or "all providers failed", "elapsed": 0.0}

    # ─────────────────────────────────────────────────────
    # Smart task-based routing
    # ─────────────────────────────────────────────────────
    TASK_ROUTING = {
        "code": {
            "role": "fast",
            "prefer": ["zai_glm_1", "zai_glm_2", "zai_glm_3", "zai_glm_4", "gemini", "qwen", "deepseek"],
        },
        "analysis": {
            "role": "smart",
            "prefer": ["zai_glm_1", "zai_glm_2", "zai_glm_3", "zai_glm_4", "gemini", "qwen", "deepseek"],
        },
        "learn": {
            "role": "smart",
            "prefer": ["zai_glm_1", "zai_glm_2", "zai_glm_3", "zai_glm_4", "gemini", "qwen", "deepseek"],
        },
        "plan": {
            "role": "smart",
            "prefer": ["zai_glm_1", "zai_glm_2", "zai_glm_3", "zai_glm_4", "gemini", "qwen"],
        },
        "quick": {
            "role": "fast",
            "prefer": ["zai_glm_1", "zai_glm_2", "zai_glm_3", "zai_glm_4", "gemini", "qwen"],
        },
    }

    def _cooldown_provider(self, name: str, seconds: int = 300) -> None:
        """Put provider in cooldown after 429."""
        self._cooldowns[name] = time.time() + seconds

    def _is_cooled_down(self, name: str) -> bool:
        """Check if provider is available (not in cooldown)."""
        return time.time() >= self._cooldowns.get(name, 0)

    def generate_for_task(self, task_type: str, prompt: str, system: str = "",
                          temperature: float = 0.2, max_tokens=None) -> Dict:
        """
        Smart routing based on task type.
        Tries preferred providers in order, falls back if all fail.
        """
        rule = self.TASK_ROUTING.get(task_type, self.TASK_ROUTING["quick"])
        role = rule["role"]
        prefer = rule["prefer"]

        last_error = ""

        for provider_name in prefer:
            result = self.generate(
                prompt=prompt,
                system=system,
                role=role,
                temperature=temperature,
                max_tokens=max_tokens,
                provider=provider_name,
                allow_fallback=False,
            )
            if result.get("ok"):
                return result
            last_error = result.get("error", "")

        # If all preferred failed, try any provider
        return self.generate(
            prompt=prompt,
            system=system,
            role=role,
            temperature=temperature,
            max_tokens=max_tokens,
        )



    # ═══════════════════════════════════════════════════════
    # Async methods (for parallel LLM calls)
    # ═══════════════════════════════════════════════════════

    async def async_generate(
        self,
        prompt: str,
        system: str = "",
        role: str = "fast",
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> Dict:
        """Async version of generate()."""
        # Run sync generate in a thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.generate(prompt, system, role, temperature, max_tokens),
        )

    async def async_generate_for_task(
        self,
        task_type: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> Dict:
        """Async version of generate_for_task()."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.generate_for_task(
                task_type, prompt, system, temperature, max_tokens
            ),
        )

    async def async_generate_batch(
        self,
        requests: List[Dict],
    ) -> List[Dict]:
        """Run multiple generate requests in parallel.

        Args:
            requests: List of dicts with keys:
                - prompt (required)
                - system (optional)
                - task_type (optional)
                - role (optional)
                - temperature (optional)
                - max_tokens (optional)

        Returns:
            List of results (same order as requests)
        """
        async def _run(req):
            if "task_type" in req:
                return await self.async_generate_for_task(
                    task_type=req["task_type"],
                    prompt=req["prompt"],
                    system=req.get("system", ""),
                    temperature=req.get("temperature", 0.2),
                    max_tokens=req.get("max_tokens", 2000),
                )
            return await self.async_generate(
                prompt=req["prompt"],
                system=req.get("system", ""),
                role=req.get("role", "fast"),
                temperature=req.get("temperature", 0.2),
                max_tokens=req.get("max_tokens", 2000),
            )

        return await asyncio.gather(*[_run(r) for r in requests])

    def list_providers(self):
        return [{"name": p.name, "priority": p.priority, "enabled": p.enabled,
                 "calls": p.calls, "failures": p.failures,
                 "models": p.models, "last_error": p.last_error}
                for p in self.providers]

    def stats(self):
        return {"total_providers": len(self.providers),
                "total_calls": sum(p.calls for p in self.providers),
                "total_failures": sum(p.failures for p in self.providers),
                "providers": self.list_providers()}


_router: Optional[LLMRouter] = None


def get_router() -> LLMRouter:
    """يُعيد الـ singleton router.

    إذا كان الـ singleton موجوداً لكن فيه mock فقط (1 provider),
    يُعيد إنشاءه لتحميل الـ providers الحقيقية.

    هذا يمنع مشكلة "الترتيب" — عندما يُحمَّل الـ singleton مبكراً
    بدون keys.
    """
    global _router
    # أعِد الإنشاء إذا:
    # - لم يكن موجوداً
    # - أو فيه mock فقط (1 provider اسمه "mock")
    needs_reload = _router is None
    if not needs_reload and hasattr(_router, "providers"):
        providers = _router.providers
        # 1 provider فقط = غالباً mock
        if len(providers) <= 1:
            needs_reload = True

    if needs_reload:
        _router = LLMRouter()
    return _router
