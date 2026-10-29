"""
LLM Orchestrator V8 — manages isolated ProviderApp instances.
Like a "launcher" that starts each LLM as a separate mini-app.
"""
import os
import logging
from pathlib import Path
from typing import Dict, List, Optional
from novamind.core.providers.base_app import ProviderApp

logger = logging.getLogger("llm_orchestrator")


class LLMOrchestrator:
    def __init__(self):
        self.apps: Dict[str, ProviderApp] = {}
        self._load_env()
        self._boot_apps()

    def _load_env(self):
        env_path = Path(os.environ.get("NOVAMIND_HOME", str(Path(__file__).resolve().parent.parent.parent))) / ".env"
        if not env_path.exists():
            return
        for line in env_path.read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

    def _boot_apps(self):
        """Boot each provider as an independent app."""
        self.apps = {}

        # ═══ GEMINI (multi-key) ═══
        for i, key_name in enumerate(["GEMINI_API_KEY", "GEMINI_API_KEY_2",
                                       "GEMINI_API_KEY_3", "GEMINI_API_KEY_4"], 1):
            key = os.environ.get(key_name, "").strip()
            if key and len(key) > 20:
                self.apps[f"gemini-{i}"] = ProviderApp(
                    name=f"gemini-{i}",
                    api_key=key,
                    base_url="https://generativelanguage.googleapis.com",
                    models={"fast": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
                            "smart": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")},
                    provider_type="gemini",
                    priority=10 + i,
                )

        # ═══ GLM / Zhipu (multi-key) ═══
        for i in range(1, 14):
            key = os.environ.get(f"ZAI_API_KEY_{i}", "").strip()
            if key and len(key) > 10:
                self.apps[f"glm-{i}"] = ProviderApp(
                    name=f"glm-{i}",
                    api_key=key,
                    base_url="https://api.z.ai/api/paas/v4",
                    models={"fast": "glm-4.5-flash", "smart": "glm-4.5-flash"},
                    provider_type="openai",
                    priority=15 + i,
                )

        # ═══ Groq Pool (20 keys with rotation) ═══
        try:
            from groq_pool import GroqKeyPool
            groq_pool = GroqKeyPool()
            for idx, key in enumerate(groq_pool.keys, 1):
                app_name = f"groq-{idx:02d}"
                self.apps[app_name] = ProviderApp(
                    name=app_name,
                    api_key=key,
                    base_url="https://api.groq.com/openai/v1",
                    models={
                        "fast": "openai/gpt-oss-120b",
                        "smart": "openai/gpt-oss-120b",
                    },
                    provider_type="openai",
                    priority=20 + idx,
                )
            logger.info(f"Loaded Groq pool: {len(groq_pool.keys)} keys")
        except ImportError as e:
            logger.warning(f"Groq pool not available: {e}")

        # ═══ OpenRouter (multi-key) ═══
        for i in range(1, 12):
            key = os.environ.get(f"OPENROUTER_API_KEY_{i}", "").strip()
            if key and len(key) > 10:
                self.apps[f"openrouter-{i}"] = ProviderApp(
                    name=f"openrouter-{i}",
                    api_key=key,
                    base_url="https://openrouter.ai/api/v1",
                    models={"fast": "meta-llama/llama-3.3-70b-instruct",
                            "smart": "anthropic/claude-3.5-sonnet"},
                    provider_type="openai",
                    priority=25 + i,
                )

        # ═══ Local Ollama ═══
        ollama_host = (os.environ.get("OLLAMA_HOST", "").strip() or
                       os.environ.get("LOCAL_LLM_HOST", "").strip())
        if ollama_host:
            if not ollama_host.startswith("http"):
                ollama_host = f"http://{ollama_host}"
            self.apps["ollama"] = ProviderApp(
                name="ollama",
                api_key="local",
                base_url=ollama_host.rstrip("/") + "/v1",
                models={
                    "fast": os.environ.get("LOCAL_MODEL_FAST", "qwen2.5-coder:7b"),
                    "smart": os.environ.get("LOCAL_MODEL_SMART", "qwen2.5-coder:7b"),
                },
                provider_type="openai",
                priority=50,
            )

        # ═══ Qwen (DashScope) ═══
        qwen_key = os.environ.get("QWEN_API_KEY", "").strip()
        if qwen_key:
            self.apps["qwen"] = ProviderApp(
                name="qwen",
                api_key=qwen_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                models={"fast": "qwen-plus", "smart": "qwen-max"},
                provider_type="openai",
                priority=60,
            )

        # ═══ DeepSeek ═══
        ds_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if ds_key:
            self.apps["deepseek"] = ProviderApp(
                name="deepseek",
                api_key=ds_key,
                base_url="https://api.deepseek.com/v1",
                models={"fast": "deepseek-chat", "smart": "deepseek-chat"},
                provider_type="openai",
                priority=70,
            )

        # ═══ OpenAI ═══
        oai_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if oai_key:
            self.apps["openai"] = ProviderApp(
                name="openai",
                api_key=oai_key,
                base_url="https://api.openai.com/v1",
                models={"fast": "gpt-4o-mini", "smart": "gpt-4o"},
                provider_type="openai",
                priority=80,
            )

        logger.info(f"Booted {len(self.apps)} provider apps: "
                    f"{list(self.apps.keys())}")

    def _sorted_apps(self) -> List[ProviderApp]:
        return sorted(self.apps.values(), key=lambda a: a.priority)

    # ═══════════════════════════════════════════════
    #  Main call with automatic failover
    # ═══════════════════════════════════════════════
    def call(self, prompt: str, task: str = "fast", system: str = "",
             temperature: float = 0.2, max_tokens: int = 2048,
             skip: Optional[List[str]] = None) -> Dict:
        """Route to first healthy app; fallback through the chain."""
        skip = set(skip or [])
        errors = []

        for app in self._sorted_apps():
            if app.name in skip:
                continue
            if not app.is_healthy():
                errors.append(f"{app.name}: cooldown ({app.stats.cooldown_reason})")
                continue

            r = app.call(prompt, task=task, system=system,
                         temperature=temperature, max_tokens=max_tokens)
            if r.get("ok"):
                return r
            errors.append(f"{app.name}: {r.get('error', '')[:80]}")

        return {
            "ok": False,
            "error": "All apps failed: " + " | ".join(errors[:5]),
            "errors": errors,
        }

    # ═══════════════════════════════════════════════
    #  Stats
    # ═══════════════════════════════════════════════
    def stats(self) -> Dict:
        return {
            "total_apps": len(self.apps),
            "healthy_apps": sum(1 for a in self.apps.values() if a.is_healthy()),
            "apps": [a.get_stats() for a in self._sorted_apps()],
        }

    def get_app(self, name: str) -> Optional[ProviderApp]:
        return self.apps.get(name)

    def reset_all_cooldowns(self):
        for a in self.apps.values():
            a.stats.cooldown_until = 0
            a.stats.cooldown_reason = ""
            a._save_state()
        logger.info("All cooldowns reset")


# Singleton
orchestrator = LLMOrchestrator()


# ─── Compatibility shim for old code ──────────────
def get_router():
    return orchestrator
