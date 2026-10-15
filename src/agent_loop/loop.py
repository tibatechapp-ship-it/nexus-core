"""Agent Loop — ReAct pattern (Thought → Action → Observation)."""
from __future__ import annotations
import os
import sys
import json
import time

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
    def __init__(self, llm=None, registry=None, max_iterations=8, verbose=True):
        self.llm = llm
        if self.llm is None:
            from novamind.core.llm_router import get_router
            self.llm = get_router()
        self.registry = registry or build_default_registry()
        self.max_iterations = max_iterations
        self.verbose = verbose
        self.trace = []

    def _log(self, icon, text):
        if self.verbose:
            print(f"{icon} {text}")
        self.trace.append({"icon": icon, "text": str(text)})

    def _call_llm(self, messages):
        """يستدعي LLM مع tools ويُرجع الرد."""
        try:
            # نحتاج استدعاء مباشر مع tools
            from openai import OpenAI

            # استخدم مزود Groq
            provider = None
            for p in self.llm.providers:
                if p.name.startswith("groq") and p.enabled:
                    provider = p
                    break

            if not provider:
                return {"ok": False, "error": "لا يوجد مزود متاح"}

            client = OpenAI(api_key=provider.api_key, base_url=provider.base_url)
            model = provider.models.get("fast", "qwen/qwen3.8-27b")

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=self.registry.to_openai(),
                tool_choice="auto",
                temperature=0.3,
                max_tokens=1000,
            )
            msg = response.choices[0].message
            return {"ok": True, "message": msg}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def run(self, user_input):
        """يشغّل الحلقة الكاملة."""
        self.trace = []
        self._log("🎯", f"المهمة: {user_input}")

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ]

        for i in range(1, self.max_iterations + 1):
            self._log("", f"--- جولة {i}/{self.max_iterations} ---")

            # 1. استدعاء LLM
            result = self._call_llm(messages)
            if not result.get("ok"):
                self._log("❌", f"خطأ LLM: {result.get('error', '')[:120]}")
                return {
                    "ok": False,
                    "error": result.get("error"),
                    "iterations": i,
                    "trace": self.trace,
                }

            msg = result["message"]
            # ═══ أضف الرسالة بحقول نظيفة فقط ═══
            assistant_msg = {"role": "assistant"}
            if msg.content:
                assistant_msg["content"] = msg.content
            if getattr(msg, "tool_calls", None):
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]
            messages.append(assistant_msg)

            # 2. هل طلب أداة؟
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                # ═══ الإجابة النهائية ═══
                answer = msg.content or "(لا إجابة)"
                self._log("✅", "الإجابة النهائية")
                return {
                    "ok": True,
                    "answer": answer,
                    "iterations": i,
                    "trace": self.trace,
                }

            # 3. نفّذ كل أداة مطلوبة
            for tc in tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}

                self._log("🔧", f"استدعاء: {name}({args})")

                # نفّذ الأداة
                t0 = time.time()
                observation = self.registry.call(name, args)
                elapsed = time.time() - t0

                preview = observation[:150].replace("\n", " ")
                self._log("📊", f"({elapsed:.2f}ث) {preview}")

                # أضف النتيجة
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": observation,
                })

        # تجاوز الحد
        self._log("⚠️", f"تجاوز {self.max_iterations} جولات")
        return {
            "ok": False,
            "error": "max_iterations_exceeded",
            "iterations": self.max_iterations,
            "trace": self.trace,
        }
