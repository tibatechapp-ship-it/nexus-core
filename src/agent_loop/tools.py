"""Tool Registry — الأدوات المتاحة للوكيل."""

from __future__ import annotations
import os
import sys
import json
import time
import inspect
import tempfile
from pathlib import Path
from typing import Any, Callable

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

# ═══ حماية أدوات الملفات (mirrors C1/C2) ═══════════════════════
try:
    from src.tools.executor import is_sensitive_file
except ImportError:

    def is_sensitive_file(path: Path) -> bool:
        return path.name in {".env", "id_rsa", "id_ed25519", "credentials"} or path.suffix in {
            ".pem",
            ".key",
            ".p12",
            ".pfx",
        }


MAX_READ = 512 * 1024
MAX_WRITE = 1024 * 1024
_SENSITIVE_DIRS = frozenset({".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker"})
_SKIP_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "dist",
        "build",
        ".idea",
        ".vscode",
        "htmlcov",
        ".coverage",
    }
)

DEV_TOOLS_ENV = "NEXUS_ENABLE_DEV_TOOLS"
MEMORY_WRITE_ENV = "NEXUS_ENABLE_MEMORY_WRITES"
_APPROVAL_TOKENS = frozenset(
    {
        "approve",
        "approved",
        "yes",
        "true",
        "1",
        "موافق",
        "موافقة",
    }
)


def dev_tools_enabled() -> bool:
    """True only when development tools were explicitly enabled in the environment."""
    return os.environ.get(DEV_TOOLS_ENV) == "1"


def memory_write_enabled() -> bool:
    """True only when memory writes were explicitly enabled in the environment."""
    return os.environ.get(MEMORY_WRITE_ENV) == "1"


def approval_granted(value: Any) -> bool:
    """True only for an explicit, narrowly defined approval decision."""
    if value is True:
        return True
    return isinstance(value, str) and value.strip().casefold() in _APPROVAL_TOKENS


def _workspace_root() -> Path:
    return Path(os.environ.get("NEXUS_AGENT_WORKSPACE", os.getcwd())).resolve()


def safe_path(rel: str) -> Path:
    """Resolve rel inside workspace; reject escapes, sensitive files, gated dirs."""
    if not rel or "\x00" in rel:
        raise ValueError("مسار غير صالح")
    workspace = _workspace_root()
    target = (workspace / rel).expanduser().resolve()
    try:
        target.relative_to(workspace)
    except ValueError:
        raise PermissionError(f"خارج مساحة العمل: {rel}")
    if any(part in _SKIP_DIRS or part in _SENSITIVE_DIRS for part in target.parts):
        raise PermissionError(f"مسار محظور: {rel}")
    if is_sensitive_file(target):
        raise PermissionError(f"ملف حساس: {rel}")
    return target


class Tool:
    def __init__(self: Any, name: Any, description: Any, func: Any, parameters: Any) -> None:
        self.name = name
        self.description = description
        self.func = func
        self.parameters = parameters

    def to_openai(self: Any) -> Any:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self: Any) -> None:
        self.tools: dict[str, Any] = {}

    def register(self: Any, name: Any, description: Any, parameters: Any) -> Any:
        def deco(fn: Any) -> Any:
            self.tools[name] = Tool(name, description, fn, parameters)
            return fn

        return deco

    def to_openai(self: Any) -> Any:
        return [t.to_openai() for t in self.tools.values()]

    def call(self: Any, name: Any, args: Any) -> Any:
        if name not in self.tools:
            return f"خطأ: أداة {name} غير موجودة"
        try:
            result = self.tools[name].func(**args)
            return str(result)[:1000]
        except Exception as e:
            return f"خطأ في {name}: {e}"


def build_default_registry(
    include_dev_tools: bool = False,
    include_memory_write: bool = False,
) -> Any:
    """Build the default read-only registry.

    Mutating tools (``write_file``) and nested-agent dispatch (``run_agent``)
    are absent unless the caller opts in **and** ``NEXUS_ENABLE_DEV_TOOLS=1``.
    Memory writes (``remember``) are absent unless the caller opts in **and**
    ``NEXUS_ENABLE_MEMORY_WRITES=1``. Even then each call requires an explicit
    ``approval`` decision.
    """
    reg = ToolRegistry()

    # ═══ 1. search_memory ═══
    @reg.register(
        "search_memory",
        "يبحث في الذاكرة الدلالية عن معلومات سابقة",
        {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    )
    def search_memory(query: Any) -> Any:
        try:
            from src.memory.agent_rag_bridge import get_bridge

            docs = get_bridge().recall(query, k=3)
            if not docs:
                return "لا توجد نتائج"
            return "\n".join(f"[{d.id}] {d.text}" for d in docs)
        except Exception as e:
            return f"خطأ: {e}"

    # ═══ 2. remember (opt-in + approval, never default) ═══
    if include_memory_write and memory_write_enabled():

        @reg.register(
            "remember",
            "يحفظ معلومة جديدة في الذاكرة (يتطلب تفعيلاً وموافقة صريحة)",
            {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "approval": {"type": ["boolean", "string"], "description": "قرار موافقة صريح"},
                },
                "required": ["text", "approval"],
            },
        )
        def remember(text: Any, approval: Any = None) -> Any:
            if not approval_granted(approval):
                return "محظور: موافقة صريحة مطلوبة لحفظ الذاكرة"
            try:
                from src.memory.agent_rag_bridge import get_bridge

                doc_id = get_bridge().remember(str(text))
                return f"تم الحفظ: {doc_id}"
            except Exception as e:
                return f"خطأ: {e}"

    # ═══ 3. list_agents ═══
    @reg.register(
        "list_agents",
        "يعرض قائمة الوكلاء المتاحين (بإمكانك اختيار فئة)",
        {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "code/security/quality/... أو فارغ للكل",
                }
            },
        },
    )
    def list_agents(category: Any = "") -> Any:
        try:
            from nova.registry import REGISTRY, agents_by_category

            if category:
                agents = agents_by_category(category)
                return f"فئة {category}: {', '.join(agents)}"
            return f"عدد الوكلاء: {len(REGISTRY)}"
        except Exception as e:
            return f"خطأ: {e}"

    # ═══ 4. run_agent (dev-bounded, never default) ═══
    if include_dev_tools and dev_tools_enabled():

        @reg.register(
            "run_agent",
            "يشغّل وكيلاً معيناً بمهمة (يتطلب تفعيلاً وموافقة صريحة)",
            {
                "type": "object",
                "properties": {
                    "agent": {"type": "string"},
                    "prompt": {"type": "string"},
                    "approval": {"type": ["boolean", "string"], "description": "قرار موافقة صريح"},
                },
                "required": ["agent", "prompt", "approval"],
            },
        )
        def run_agent(agent: Any, prompt: Any, approval: Any = None) -> Any:
            if not approval_granted(approval):
                return "محظور: موافقة صريحة مطلوبة لتشغيل وكيل"
            try:
                from nova.registry import REGISTRY

                ag = REGISTRY.load_agent(agent)
                methods = ["build", "run", "execute", "analyze", "fix", "review", "generate"]
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
        {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    )
    def read_file(path: Any) -> Any:
        try:
            p = safe_path(str(path))
            if not p.exists():
                return f"ملف غير موجود: {p.name}"
            size = p.stat().st_size
            if size > MAX_READ:
                return f"الملف كبير جداً ({size} بايت > {MAX_READ // 1024}KB)"
            with open(p, encoding="utf-8", errors="replace") as f:
                return f.read()[:2000]
        except PermissionError as e:
            return f"محظور: {e}"
        except Exception as e:
            return f"خطأ: {e}"

    # ═══ 6. get_time ═══
    @reg.register("get_time", "يُرجع الوقت والتاريخ الحالي", {"type": "object", "properties": {}})
    def get_time() -> Any:
        return time.strftime("%Y-%m-%d %H:%M:%S")

    # ═══ 7. write_file (dev-bounded, never default) ═══
    if include_dev_tools and dev_tools_enabled():

        @reg.register(
            "write_file",
            "يكتب محتوى إلى ملف داخل مساحة العمل فقط (تفعيل وموافقة صريحة)",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "approval": {"type": ["boolean", "string"], "description": "قرار موافقة صريح"},
                },
                "required": ["path", "content", "approval"],
            },
        )
        def write_file(path: Any, content: Any, approval: Any = None) -> Any:
            if not approval_granted(approval):
                return "محظور: موافقة صريحة مطلوبة للكتابة"
            try:
                p = safe_path(str(path))
                body = str(content)
                if len(body.encode("utf-8")) > MAX_WRITE:
                    return f"المحتوى كبير جداً (> {MAX_WRITE // 1024}KB)"
                if p.suffix == ".py":
                    try:
                        compile(body, str(p), "exec")
                    except SyntaxError as e:
                        return f"خطأ صياغة سطر {e.lineno}: {e.msg} — لم يُحفظ"
                p.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".agent-tmp-", suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        fh.write(body)
                    os.replace(tmp, p)
                except Exception:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                    raise
                return f"تم الكتابة: {p.name} ({len(body)} حرف)"
            except PermissionError as e:
                return f"محظور: {e}"
            except Exception as e:
                return f"خطأ: {e}"

    # ═══ 8. list_files ═══
    @reg.register(
        "list_files",
        "يعرض ملفات مجلد",
        {
            "type": "object",
            "properties": {"directory": {"type": "string"}},
            "required": ["directory"],
        },
    )
    def list_files(directory: Any) -> Any:
        try:
            p = safe_path(str(directory))
            if not p.is_dir():
                return f"مجلد غير موجود: {p.name}"
            files = []
            for name in sorted(os.listdir(p)):
                entry = p / name
                if any(part in _SKIP_DIRS or part in _SENSITIVE_DIRS for part in entry.parts):
                    continue
                if is_sensitive_file(entry):
                    continue
                files.append(name)
                if len(files) >= 30:
                    break
            return "\n".join(files) if files else "(لا ملفات)"
        except PermissionError as e:
            return f"محظور: {e}"
        except Exception as e:
            return f"خطأ: {e}"

    return reg
