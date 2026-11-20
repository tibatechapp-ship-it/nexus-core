"""Agent Loop — ReAct pattern (Thought → Action → Observation)."""
from __future__ import annotations
import os
import sys
import json
import time
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from src.agent_loop.tools import build_default_registry


SYSTEM_PROMPT = """أنت وكيل ذكي يستخدم الأدوات لحل المهام.

اتبع هذا النمط بدقة:
1. **فكر** (Thought): حلّل ما تحتاجه.
2. **استخدم أداة** (Action): إذا احتجت معلومات، استدعِ الأداة المناسبة.
3. **لاحظ** (Observation): اقرأ النتيجة.
4. **كرر** حتى تحل المهمة.
5. **أجب** (Answer): أعطِ الإجابة النهائية.

قواعد:
- لا تخترع معلومات — استخدم الأدوات.
- إذا لم تحتج أداة، أجب مباشرة.
- استخدم الأدوات بالعربية أو الإنجليزية — كلاهما يعمل.
- لا تستخدم أكثر من أداة في كل خطوة."""


class AgentLoop:
    def __init__(
        self,
        llm: Any = None,
        registry: Any = None,
        max_iterations: int = 8,
        verbose: bool = True,
    ) -> None:
        self.llm = llm
        if self.llm is None:
            from novamind.core.llm_router import get_router
            self.llm = get_router()
        self.registry = registry or build_default_registry()
        self.max_iterations = max_iterations
        self.verbose = verbose
        self.trace: list[dict[str, Any]] = []

    def _log(self, icon: str, text: Any) -> None:
        if self.verbose:
            print(f"{icon} {text}")
        self.trace.append({"icon": icon, "text": str(text)})

    def _call_llm(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Call an enabled real OpenAI-compatible provider with tool support."""
        compatible = {
            "groq", "zai", "openrouter", "mistral", "deepseek",
            "qwen", "openai", "ollama",
        }
        providers = [
            provider for provider in getattr(self.llm, "providers", [])
            if getattr(provider, "enabled", False)
            and str(getattr(provider, "name", "")).split("_", 1)[0].lower() in compatible
            and (
                getattr(provider, "api_key", None)
                or str(getattr(provider, "name", "")).split("_", 1)[0].lower() == "ollama"
            )
            and getattr(provider, "base_url", None)
        ]
        if not providers:
            return {
                "ok": False,
                "status": "llm_unavailable",
                "error": "No enabled real OpenAI-compatible tool-calling provider is configured",
            }

        try:
            from openai import OpenAI
        except ImportError:
            return {
                "ok": False,
                "status": "llm_dependency_missing",
                "error": "The openai client package is required for tool-calling providers",
            }

        errors = []
        for provider in providers:
            model = getattr(provider, "models", {}).get("fast")
            if not model:
                errors.append(f"{provider.name}:missing_model")
                continue
            try:
                client = OpenAI(
                    api_key=getattr(provider, "api_key", None) or "ollama",
                    base_url=provider.base_url,
                    timeout=30.0,
                    max_retries=0,
                )
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=self.registry.to_openai(),
                    tool_choice="auto",
                    temperature=0.3,
                    max_tokens=1000,
                )
                if not getattr(response, "choices", None):
                    raise RuntimeError("empty provider choices")
                message = response.choices[0].message
                if not getattr(message, "content", None) and not getattr(message, "tool_calls", None):
                    raise RuntimeError("empty provider message")
                return {
                    "ok": True,
                    "simulated": False,
                    "provider": provider.name,
                    "model": model,
                    "message": message,
                }
            except Exception as exc:
                errors.append(f"{provider.name}:{type(exc).__name__}")

        return {
            "ok": False,
            "status": "llm_provider_error",
            "error": "All configured tool-calling providers failed: " + ", ".join(errors),
        }

    def run(self, user_input: str) -> dict[str, Any]:
        """Run the tool loop; only a real, identified provider can complete it."""
        self.trace = []
        self._log("🎯", f"المهمة: {user_input}")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ]
        providers_used: list[str] = []

        for iteration in range(1, self.max_iterations + 1):
            self._log("", f"--- جولة {iteration}/{self.max_iterations} ---")
            result = self._call_llm(messages)
            if not isinstance(result, dict) or result.get("ok") is not True:
                error = result.get("error", "Invalid LLM response") if isinstance(result, dict) else "Invalid LLM response"
                self._log("❌", f"خطأ LLM: {str(error)[:120]}")
                return {
                    "ok": False,
                    "status": result.get("status", "llm_provider_error") if isinstance(result, dict) else "invalid_llm_response",
                    "error": str(error)[:300],
                    "iterations": iteration,
                    "providers_used": providers_used,
                    "trace": self.trace,
                }

            provider = str(result.get("provider") or "").strip()
            if result.get("simulated") or not provider or provider.lower() in {"mock", "offline"}:
                return {
                    "ok": False,
                    "status": "simulated_or_unidentified_provider",
                    "error": "AgentLoop rejected simulated or unidentified provider output",
                    "iterations": iteration,
                    "providers_used": providers_used,
                    "trace": self.trace,
                }
            if provider not in providers_used:
                providers_used.append(provider)

            message = result.get("message")
            if message is None:
                return {
                    "ok": False, "status": "invalid_llm_response",
                    "error": "LLM response did not include a message",
                    "iterations": iteration, "providers_used": providers_used,
                    "trace": self.trace,
                }

            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if getattr(message, "content", None):
                assistant_msg["content"] = message.content
            tool_calls = getattr(message, "tool_calls", None)
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in tool_calls
                ]
            messages.append(assistant_msg)

            if not tool_calls:
                answer = message.content
                if not isinstance(answer, str) or not answer.strip():
                    return {
                        "ok": False, "status": "empty_llm_response",
                        "error": "LLM returned neither a final answer nor tool calls",
                        "iterations": iteration, "providers_used": providers_used,
                        "trace": self.trace,
                    }
                self._log("✅", "الإجابة النهائية")
                return {
                    "ok": True,
                    "status": "success",
                    "simulated": False,
                    "provider": provider,
                    "model": result.get("model"),
                    "providers_used": providers_used,
                    "answer": answer,
                    "iterations": iteration,
                    "trace": self.trace,
                }

            for tool_call in tool_calls:
                name = tool_call.function.name
                try:
                    arguments = json.loads(tool_call.function.arguments or "{}")
                    if not isinstance(arguments, dict):
                        raise ValueError("tool arguments must be a JSON object")
                except (TypeError, ValueError, json.JSONDecodeError):
                    return {
                        "ok": False, "status": "invalid_tool_arguments",
                        "error": f"Tool {name} returned invalid JSON arguments",
                        "iterations": iteration, "providers_used": providers_used,
                        "trace": self.trace,
                    }

                self._log("🔧", f"استدعاء: {name}")
                started = time.time()
                try:
                    observation = self.registry.call(name, arguments)
                except Exception as exc:
                    return {
                        "ok": False, "status": "tool_execution_failed",
                        "error": f"{name}: {type(exc).__name__}",
                        "iterations": iteration, "providers_used": providers_used,
                        "trace": self.trace,
                    }
                elapsed = time.time() - started
                preview = str(observation)[:150].replace("\n", " ")
                self._log("📊", f"({elapsed:.2f}ث) {preview}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(observation),
                })

        self._log("⚠️", f"تجاوز {self.max_iterations} جولات")
        return {
            "ok": False,
            "status": "max_iterations_exceeded",
            "error": "max_iterations_exceeded",
            "iterations": self.max_iterations,
            "providers_used": providers_used,
            "trace": self.trace,
        }
