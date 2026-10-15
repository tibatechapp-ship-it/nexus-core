"""ToolAgent — Gemini 3.x with full functionCall preservation."""
import asyncio
import json
import logging
import os
from typing import List, Dict, Any, Optional

import httpx

try:
    from hive.tools import get_registry, execute_tool_calls
except ImportError:
    from novamind.core.hive.tools import get_registry, execute_tool_calls

logger = logging.getLogger("ToolAgent")

SYSTEM_PROMPT = """أنت مساعد ذكي لديك وصول لأدوات حقيقية.

**القواعد:**
1. إذا احتجت معلومة، استخدم الأدوات — لا تخمّن.
2. بعد كل أداة، اقرأ النتيجة ثم قرر الخطوة التالية.
3. **كن اقتصاديًا:** استدعِ أقل عدد ممكن من الأدوات (2-3 مثالي).
4. لا تستدعِ نفس الأداة مرتين — إذا لم تنجح، جرّب طريقة أخرى.
5. أجب بالعربية أو الإنجليزية حسب السؤال.
6. إذا كانت المعلومة معروفة، أجب مباشرة بدون أدوات.
"""

MAX_TOOL_CALLS = 10
GEMINI_API_TPL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/{model}:generateContent?key={key}"
)

GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest",
]

_WORKING_MODEL: Optional[str] = None
_WORKING_KEY: Optional[str] = None


def _all_gemini_keys() -> List[str]:
    keys = []
    for i in range(1, 21):
        k = os.getenv(f"GEMINI_API_KEY_{i}", "").strip()
        if k.startswith("AIza") or k.startswith("AQ."):
            keys.append(k)
    single = os.getenv("GEMINI_API_KEY", "").strip()
    if single and single not in keys:
        keys.append(single)
    return keys


class ToolAgent:
    def __init__(self, max_tool_calls: int = MAX_TOOL_CALLS):
        self.max_tool_calls = max_tool_calls
        self.registry = get_registry()

    async def _try_one(self, client, key, model, payload):
        try:
            url = GEMINI_API_TPL.format(model=model, key=key)
            r = await client.post(url, json=payload)
            if r.status_code == 200:
                return {"ok": True, "data": r.json(), "model": model, "key": key}
            return {
                "ok": False, "status": r.status_code,
                "error": f"{model}: HTTP {r.status_code} — {r.text[:300]}",
                "model": model, "key": key,
            }
        except Exception as e:
            return {"ok": False, "status": 0, "error": f"{model}: {e}",
                    "model": model, "key": key}

    async def _call_gemini(self, client, contents, tools):
        global _WORKING_MODEL, _WORKING_KEY

        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": contents,
            "tools": [{"function_declarations": tools}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
        }

        keys = _all_gemini_keys()
        if not keys:
            return {"ok": False, "error": "No Gemini keys"}

        if _WORKING_MODEL and _WORKING_KEY and _WORKING_KEY in keys:
            r = await self._try_one(client, _WORKING_KEY, _WORKING_MODEL, payload)
            if r["ok"]:
                logger.info(f"✓ cached {_WORKING_MODEL}")
                return r
            if r.get("status") == 404:
                logger.warning(f"Cached model {_WORKING_MODEL} no longer valid")

        last_error = ""
        for key in keys[:5]:
            for model in GEMINI_MODELS:
                r = await self._try_one(client, key, model, payload)
                if r["ok"]:
                    _WORKING_MODEL = model
                    _WORKING_KEY = key
                    logger.info(f"✓ new {model} (key ...{key[-8:]})")
                    return r

                last_error = r["error"]

                if r.get("status") == 429:
                    await asyncio.sleep(0.3)
                    break
                if r.get("status") == 404:
                    continue
                if r.get("status") == 400:
                    logger.warning(f"400 (payload): {r['error'][:120]}")
                    continue
                if r.get("status") in (401, 403):
                    break
                await asyncio.sleep(0.2)

        return {"ok": False, "error": f"All failed. Last: {last_error}"}

    async def chat(self, user_message: str,
                   context: Optional[List[Dict]] = None) -> Dict[str, Any]:
        tools = self.registry.to_gemini_schemas()
        if not tools:
            return {"ok": False, "error": "No tools registered"}

        contents = []
        if context:
            contents.extend(context)
        contents.append({"role": "user", "parts": [{"text": user_message}]})

        executed_tools = []
        iteration = 0
        used_model = None

        async with httpx.AsyncClient(timeout=120.0) as client:
            while iteration < self.max_tool_calls:
                iteration += 1

                resp = await self._call_gemini(client, contents, tools)
                if not resp["ok"]:
                    return {"ok": False, "error": resp["error"],
                            "tool_calls": executed_tools,
                            "iterations": iteration}

                used_model = resp["model"]
                data = resp["data"]

                candidate = data.get("candidates", [{}])[0]
                content = candidate.get("content", {})
                parts = content.get("parts", [])

                function_calls = [p for p in parts if "functionCall" in p]

                if not function_calls:
                    text = "".join(p.get("text", "") for p in parts if "text" in p)
                    return {
                        "ok": True,
                        "reply": text.strip() or "(لا رد)",
                        "tool_calls": executed_tools,
                        "iterations": iteration,
                        "model": used_model,
                    }

                # ═══ احفظ الـ parts كما هي — حرفياً ═══
                # هذا يضمن preservation لـ thought_signature
                contents.append({
                    "role": "model",
                    "parts": parts,   # ← كامل، بلا فلترة
                })

                # ═══ اجمع أدوات التنفيذ ═══
                calls_to_exec = []
                for p in parts:
                    if "functionCall" not in p:
                        continue
                    fn = p["functionCall"]
                    calls_to_exec.append({
                        "id": f"call_{len(calls_to_exec)+1}",
                        "name": fn.get("name", ""),
                        "arguments": fn.get("args", {}),
                    })

                logger.info(f"Executing {len(calls_to_exec)} tools")
                results = await execute_tool_calls(calls_to_exec)

                # ═══ نتائج الأدوات — بصيغة Gemini الصحيحة ═══
                tool_response_parts = []
                for call, result in zip(calls_to_exec, results):
                    tool_response_parts.append({
                        "functionResponse": {
                            "name": call["name"],
                            "response": {"output": result["result"]}
                        }
                    })
                    executed_tools.append({
                        "name": call["name"],
                        "arguments": call["arguments"],
                        "ok": result["ok"],
                        "result": result["result"][:500],
                    })

                contents.append({
                    "role": "user",
                    "parts": tool_response_parts,
                })

                await asyncio.sleep(0.5)

        return {
            "ok": False,
            "error": f"Too many tool calls (>{self.max_tool_calls})",
            "tool_calls": executed_tools,
            "iterations": iteration,
        }


_agent: Optional[ToolAgent] = None

def get_tool_agent() -> ToolAgent:
    global _agent
    if _agent is None:
        _agent = ToolAgent()
    return _agent
