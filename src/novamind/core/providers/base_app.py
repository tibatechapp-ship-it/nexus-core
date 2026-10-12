"""
ProviderApp — Base class for each isolated LLM provider.
Each provider behaves like a standalone mini-app:
- Own state file (memory/providers/<name>.json)
- Own log file (logs/providers/<name>.log)
- Own client, cooldown, stats
"""
import os
import json
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict

BASE_DIR = Path(os.environ.get("NOVAMIND_HOME", str(Path(__file__).resolve().parent.parent)))
STATE_DIR = BASE_DIR / "memory" / "providers"
LOG_DIR = BASE_DIR / "logs" / "providers"
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _get_app_logger(app_name: str) -> logging.Logger:
    """Each app gets its own file logger."""
    logger = logging.getLogger(f"provider.{app_name}")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False

    fh = logging.FileHandler(LOG_DIR / f"{app_name}.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(fh)
    return logger


@dataclass
class ProviderStats:
    name: str = ""
    calls: int = 0
    successes: int = 0
    failures: int = 0
    rate_limits: int = 0
    server_errors: int = 0
    auth_errors: int = 0
    total_latency_ms: float = 0.0
    last_call_at: float = 0.0
    last_success_at: float = 0.0
    last_error: str = ""
    last_error_at: float = 0.0
    cooldown_until: float = 0.0
    cooldown_reason: str = ""

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.successes if self.successes else 0.0

    @property
    def success_rate(self) -> float:
        return (self.successes / self.calls * 100) if self.calls else 0.0

    def is_healthy(self) -> bool:
        return time.time() >= self.cooldown_until


class ProviderApp:
    """
    One isolated LLM provider app.
    Behaves like its own standalone service.
    """
    COOLDOWN_RATE_LIMIT = 3600
    COOLDOWN_SERVER_ERROR = 300
    COOLDOWN_TIMEOUT = 60
    COOLDOWN_AUTH_ERROR = 86400

    def __init__(self, name: str, api_key: str, base_url: str,
                 models: Dict[str, str], provider_type: str = "openai",
                 priority: int = 100):
        self.name = name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.models = models
        self.provider_type = provider_type  # "gemini" | "openai"
        self.priority = priority

        self.log = _get_app_logger(name)
        self.state_file = STATE_DIR / f"{name}.json"
        self.stats = self._load_state()
        self._client: Optional[Any] = None

        self.log.info(f"[{name}] app initialized (type={provider_type}, "
                      f"priority={priority})")

    # ─── State persistence ────────────────────────────
    def _load_state(self) -> ProviderStats:
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                return ProviderStats(**{k: v for k, v in data.items()
                                        if k in ProviderStats.__dataclass_fields__})
            except Exception as e:
                self.log.warning(f"[{self.name}] state load failed: {e}")
        return ProviderStats(name=self.name)

    def _save_state(self):
        try:
            self.state_file.write_text(
                json.dumps(asdict(self.stats), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            self.log.error(f"[{self.name}] state save failed: {e}")

    # ─── Client ───────────────────────────────────────
    def _get_client(self):
        if self._client is not None:
            return self._client

        if self.provider_type == "gemini":
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        else:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)

        self.log.info(f"[{self.name}] client created")
        return self._client

    # ─── Health ───────────────────────────────────────
    def is_healthy(self) -> bool:
        return self.stats.is_healthy()

    def cooldown_remaining(self) -> int:
        return max(0, int(self.stats.cooldown_until - time.time()))

    # ─── Error classification ─────────────────────────
    def _classify_error(self, err_str: str) -> tuple:
        e = err_str.lower()
        if "429" in err_str or "resource_exhausted" in e or "quota" in e or "rate" in e:
            return ("rate_limit", self.COOLDOWN_RATE_LIMIT)
        if "503" in err_str or "502" in err_str or "500" in err_str or "unavailable" in e:
            return ("server_error", self.COOLDOWN_SERVER_ERROR)
        if "401" in err_str or "403" in err_str or "invalid api" in e or "unauthorized" in e:
            return ("auth_error", self.COOLDOWN_AUTH_ERROR)
        return ("unknown", self.COOLDOWN_TIMEOUT)

    def _mark_failure(self, err: Exception):
        err_str = str(err)[:300]
        self.stats.failures += 1
        self.stats.last_error = err_str
        self.stats.last_error_at = time.time()

        reason, cooldown = self._classify_error(err_str)
        self.stats.cooldown_until = time.time() + cooldown
        self.stats.cooldown_reason = reason

        if reason == "rate_limit":
            self.stats.rate_limits += 1
        elif reason == "server_error":
            self.stats.server_errors += 1
        elif reason == "auth_error":
            self.stats.auth_errors += 1

        self.log.warning(f"[{self.name}] FAILURE ({reason}) "
                         f"cooldown={cooldown}s: {err_str[:150]}")
        self._save_state()

    def _mark_success(self, latency_ms: float):
        self.stats.successes += 1
        self.stats.total_latency_ms += latency_ms
        self.stats.last_success_at = time.time()
        self.stats.cooldown_until = 0
        self.stats.cooldown_reason = ""
        self._save_state()

    # ─── Task routing ─────────────────────────────────
    def _resolve_model(self, task: str) -> str:
        if task in self.models:
            return self.models[task]
        return self.models.get("fast") or next(iter(self.models.values()), "")

    # ─── Core calls ───────────────────────────────────
    def _call_gemini(self, model: str, prompt: str, system: str,
                      temperature: float, max_tokens: int) -> str:
        client = self._get_client()
        full = f"{system}\n\n{prompt}" if system else prompt

        # Try with config (disable AFC, set temperature)
        try:
            from google.genai import types
            config = types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
            resp = client.models.generate_content(
                model=model,
                contents=full,
                config=config,
            )
        except Exception:
            # Fallback: no config
            resp = client.models.generate_content(model=model, contents=full)

        return resp.text or ""

    def _call_openai(self, model: str, prompt: str, system: str,
                      temperature: float, max_tokens: int) -> str:
        client = self._get_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model=model, messages=messages,
            temperature=temperature, max_tokens=max_tokens,
        )
        return resp.choices[0].message.content

    # ─── Public call ──────────────────────────────────
    def call(self, prompt: str, task: str = "fast", system: str = "",
             temperature: float = 0.2, max_tokens: int = 2048,
             _retries: int = 2) -> Dict:
        """One isolated call with retry. Never raises."""
        if not self.is_healthy():
            return {
                "ok": False,
                "provider": self.name,
                "error": f"in cooldown ({self.stats.cooldown_reason}, "
                         f"{self.cooldown_remaining()}s left)",
            }

        # Retry on network errors
        for _attempt in range(_retries):
            result = self._call_once(prompt, task, system, temperature, max_tokens)
            if result.get("ok"):
                return result
            err = str(result.get("error", ""))
            if "Errno -3" in err or "Try again" in err or "timeout" in err.lower():
                import time as _t
                _t.sleep(2 ** _attempt)
                continue
            return result
        return result

    def _call_once(self, prompt: str, task: str = "fast", system: str = "",
                    temperature: float = 0.2, max_tokens: int = 2048) -> Dict:

        model = self._resolve_model(task)
        self.stats.calls += 1
        self.stats.last_call_at = time.time()
        t0 = time.time()

        try:
            if self.provider_type == "gemini":
                text = self._call_gemini(model, prompt, system, temperature, max_tokens)
            else:
                text = self._call_openai(model, prompt, system, temperature, max_tokens)

            latency = (time.time() - t0) * 1000
            self._mark_success(latency)
            self.log.info(f"[{self.name}] OK model={model} latency={latency:.0f}ms")

            return {
                "ok": True,
                "text": text,
                "provider": self.name,
                "model": model,
                "latency_ms": round(latency, 1),
            }
        except Exception as e:
            self._mark_failure(e)
            return {
                "ok": False,
                "provider": self.name,
                "error": str(e)[:200],
            }

    # ─── Public stats ─────────────────────────────────
    def get_stats(self) -> Dict:
        return {
            "name": self.name,
            "type": self.provider_type,
            "priority": self.priority,
            "models": self.models,
            "healthy": self.is_healthy(),
            "cooldown_remaining_sec": self.cooldown_remaining(),
            "cooldown_reason": self.stats.cooldown_reason,
            "calls": self.stats.calls,
            "successes": self.stats.successes,
            "failures": self.stats.failures,
            "rate_limits": self.stats.rate_limits,
            "server_errors": self.stats.server_errors,
            "auth_errors": self.stats.auth_errors,
            "success_rate": round(self.stats.success_rate, 1),
            "avg_latency_ms": round(self.stats.avg_latency_ms, 1),
            "last_error": self.stats.last_error[:150],
        }
