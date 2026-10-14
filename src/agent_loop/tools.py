"""Tool Registry — الأدوات المتاحة للوكيل."""
from __future__ import annotations
import os
import sys
import json
import time
import inspect

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))


class Tool:
    def __init__(self, name, description, func, parameters):
        self.name = name
        self.description = description
        self.func = func
        self.parameters = parameters

    def to_openai(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }


class ToolRegistry:
    def __init__(self):
        self.tools = {}

    def register(self, name, description, parameters):
        def deco(fn):
            self.tools[name] = Tool(name, description, fn, parameters)
            return fn
        return deco

    def to_openai(self):
        return [t.to_openai() for t in self.tools.values()]

    def call(self, name, args):
        if name not in self.tools:
            return f"خطأ: أداة {name} غير موجودة"
        try:
            result = self.tools[name].func(**args)
            return str(result)[:1000]
        except Exception as e:
            return f"خطأ في {name}: {e}"


def build_default_registry():
    """يبني السجل الافتراضي بالأدوات الست."""
    reg = ToolRegistry()

    # ═══ 1. search_memory ═══
    @reg.register(
        "search_memory",
        "يبحث في الذاكرة الدلالية عن معلومات سابقة",
        {"type": "object",
         "properties": {"query": {"type": "string"}},
         "required": ["query"]})
    def search_memory(query):
        try:
            from src.memory.agent_rag_bridge import get_bridge
            docs = get_bridge().recall(query, k=3)
            if not docs:
                return "لا توجد نتائج"
            return "\n".join(f"[{d.id}] {d.text}" for d in docs)
        except Exception as e:
            return f"خطأ: {e}"

    # ═══ 2. remember ═══
    @reg.register(
        "remember",
        "يحفظ معلومة جديدة في الذاكرة",
        {"type": "object",
         "properties": {"text": {"type": "string"}},
         "required": ["text"]})
    def remember(text):
        try:
            from src.memory.agent_rag_bridge import get_bridge
            doc_id = get_bridge().remember(text)
            return f"تم الحفظ: {doc_id}"
        except Exception as e:
            return f"خطأ: {e}"

    # ═══ 3. list_agents ═══
    @reg.register(
        "list_agents",
        "يعرض قائمة الوكلاء المتاحين (بإمكانك اختيار فئة)",
        {"type": "object",
         "properties": {
             "category": {"type": "string",
                          "description": "code/security/quality/... أو فارغ للكل"}
         }})
    def list_agents(category=""):
        try:
            from nova.registry import REGISTRY, agents_by_category
            if category:
                agents = agents_by_category(category)
                return f"فئة {category}: {', '.join(agents)}"
            return f"عدد الوكلاء: {len(REGISTRY)}"
        except Exception as e:
            return f"خطأ: {e}"

    # ═══ 4. run_agent ═══
    @reg.register(
        "run_agent",
        "يشغّل وكيلاً معيناً بمهمة",
        {"type": "object",
         "properties": {
             "agent": {"type": "string"},
             "prompt": {"type": "string"}
         },
         "required": ["agent", "prompt"]})
    def run_agent(agent, prompt):
        try:
            from nova.registry import REGISTRY
            ag = REGISTRY.load_agent(agent)
            methods = ["build", "run", "execute", "analyze",
                       "fix", "review", "generate"]
            m = next((x for x in methods if hasattr(ag, x)), None)
            if not m:
                return f"الوكيل {agent} لا يملك طريقة"
            return str(getattr(ag, m)(prompt))[:800]
        except Exception as e:
            return f"خطأ: {e}"

    # ═══ 5. read_file ═══
    @reg.register(
        "read_file",
        "يقرأ محتوى ملف",
        {"type": "object",
         "properties": {"path": {"type": "string"}},
         "required": ["path"]})
    def read_file(path):
        try:
            if not os.path.exists(path):
                return f"ملف غير موجود: {path}"
            if os.path.getsize(path) > 100_000:
                return "الملف كبير جداً"
            with open(path, encoding="utf-8") as f:
                return f.read()[:2000]
        except Exception as e:
            return f"خطأ: {e}"

    # ═══ 6. get_time ═══
    @reg.register(
        "get_time",
        "يُرجع الوقت والتاريخ الحالي",
        {"type": "object", "properties": {}})
    def get_time():
        return time.strftime("%Y-%m-%d %H:%M:%S")

    return reg
