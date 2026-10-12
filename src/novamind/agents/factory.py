"""
Agent Factory — مصنع الوكلاء الموحد v3.
- يقرأ REGISTRY من nova._registry
- يدعم aliases تلقائياً
- يضمن .name على كل وكيل
- يحترم role: tool vs manager
"""
import sys as _sys_fx
from pathlib import Path as _Path_fx

_NM_ROOT = _Path_fx(__file__).resolve().parents[1]
if str(_NM_ROOT) not in _sys_fx.path:
    _sys_fx.path.insert(0, str(_NM_ROOT))

import logging
import importlib
from typing import Dict, List, Optional, Any

logger = logging.getLogger("agents.factory")

_CANDIDATE_METHODS = [
    "run", "execute", "analyze", "process", "handle",
    "call", "__call__", "main", "invoke",
]

# خريطة: method المُعلَن → بدائل معروفة
_METHOD_ALIASES = {
    "run": ["build", "fix", "review", "learn", "generate", "analyze", "execute"],
    "coder": ["build"],
    "fixer": ["fix"],
    "code_review": ["review"],
    "learner": ["learn"],
    "test_generator": ["generate"],
}

# خريطة: method المُعلَن → بدائل معروفة
_METHOD_ALIASES = {
    "run": ["build", "fix", "review", "learn", "generate", "analyze", "execute"],
    "coder": ["build"],
    "fixer": ["fix"],
    "code_review": ["review"],
    "learner": ["learn"],
    "test_generator": ["generate"],
}


def _ensure_name_attribute(agent: Any, name: str) -> None:
    if hasattr(agent, "name"):
        return
    try:
        agent.name = name
    except (AttributeError, TypeError):
        try:
            type(agent).name = property(lambda self, _n=name: _n)
        except Exception as e:
            logger.debug(f"cannot add .name to {type(agent).__name__}: {e}")


def _resolve_main_method(cls: type, declared: Optional[str], name: str = "") -> Optional[str]:
    """يبحث عن method رئيسي — مع دعم aliases."""
    if declared and hasattr(cls, declared):
        return declared
    # جرّب aliases للاسم
    if name in _METHOD_ALIASES:
        for alias in _METHOD_ALIASES[name]:
            if hasattr(cls, alias):
                return alias
    # جرّب candidates العامة
    for candidate in _CANDIDATE_METHODS:
        if hasattr(cls, candidate):
            return candidate
    return None


class AgentFactory:
    def __init__(self) -> None:
        self._cache: Dict[str, Any] = {}
        self._registry: Dict[str, tuple] = self._build_from_source()
        self._roles: Dict[str, str] = self._build_roles()

    def _build_from_source(self) -> Dict[str, tuple]:
        try:
            from novamind.registry import all_agent_names, agent as _meta
        except ImportError as e:
            logger.error(f"❌ cannot import novamind.registry: {e}")
            return {}

        reg = {}
        for name in all_agent_names():
            try:
                m = _meta(name)
            except Exception as e:
                logger.warning(f"⚠️  {name}: cannot load meta ({e})")
                continue

            module_short = m["module"]  # e.g. "novamind.agents.a11y_agent"

            reg[name] = (module_short, m["class_name"], m.get("main_function"))

        logger.info(f"✅ Registry built: {len(reg)} agents")
        return reg

    def _build_roles(self) -> Dict[str, str]:
        """يقرأ role لكل وكيل."""
        try:
            from novamind.registry import load_registry
            data = load_registry()
            return {
                name: m.get("role", "tool")
                for name, m in data["agents"].items()
            }
        except Exception as e:
            logger.warning(f"⚠️  _build_roles failed: {e}")
            return {}

    @property
    def REGISTRY(self) -> Dict[str, tuple]:
        return self._registry

    def get_role(self, name: str) -> str:
        """role: tool | manager."""
        return self._roles.get(name, "tool")

    def get(self, name: str) -> Optional[Any]:
        if name in self._cache:
            return self._cache[name]

        canonical = name
        if name not in self._registry:
            try:
                from novamind.registry import alias_index
                canonical = alias_index().get(name, name)
            except Exception:
                pass

            if canonical not in self._registry:
                logger.warning(f"Agent not registered: {name}")
                return None

        module_short, class_name, declared_method = self._registry[canonical]
        role = self._roles.get(canonical, "tool")

        try:
            module_path = module_short if module_short.startswith("novamind.") else f"novamind.{module_short}"
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)

            try:
                agent = cls()
            except TypeError:
                agent = cls

            _ensure_name_attribute(agent, canonical)

            # إصلاح method (فقط للـ tool agents)
            if role == "tool":
                if declared_method and not hasattr(agent, declared_method):
                    resolved = _resolve_main_method(
                        cls if isinstance(cls, type) else type(agent),
                        declared_method,
                    )
                    if resolved:
                        self._registry[canonical] = (module_short, class_name, resolved)

            self._cache[canonical] = agent
            if canonical != name:
                self._cache[name] = agent
            return agent

        except Exception as e:
            logger.error(f"❌ error loading {canonical}: {type(e).__name__}: {e}")
            return None

    def list_all(self) -> List[str]:
        return list(self._registry.keys())

    def list_available(self) -> List[str]:
        """alias للتوافق الخلفي."""
        return self.list_all()

    def list_all_with_aliases(self) -> List[str]:
        try:
            from novamind.registry import all_agent_names_with_aliases
            return all_agent_names_with_aliases()
        except Exception:
            return self.list_all()

    def register(self, name: str, module_path: str,
                 class_name: str, method: str) -> None:
        self._registry[name] = (module_path, class_name, method)

    def call(self, name: str, *args, **kwargs) -> Dict:
        agent = self.get(name)
        if agent is None:
            return {"ok": False, "error": f"agent '{name}' not available"}

        canonical = name
        if canonical not in self._registry:
            try:
                from novamind.registry import alias_index
                canonical = alias_index().get(name, name)
            except Exception:
                pass

        entry = self._registry.get(canonical)
        if entry is None:
            return {"ok": False, "error": f"agent '{name}' has no registry entry"}

        _, _, method_name = entry
        if not method_name:
            resolved = _resolve_main_method(type(agent), None)
            if resolved:
                method_name = resolved
                self._registry[canonical] = (entry[0], entry[1], resolved)

        if not method_name:
            return {"ok": False, "error": f"agent '{name}' has no callable method"}

        func = getattr(agent, method_name, None)
        if func is None:
            return {"ok": False, "error": f"method '{method_name}' not found"}

        try:
            result = func(*args, **kwargs)
            if isinstance(result, dict):
                return result
            return {"ok": True, "result": result}
        except Exception as e:
            logger.exception(f"agent {name} error")
            return {"ok": False, "error": str(e)[:200]}

    def stats(self) -> Dict:
        """إحصاءات المصنع — مع توافق خلفي للـ API القديم."""
        total = len(self._registry)
        failed = 0
        errors = []
        for name in self._registry:
            try:
                if self.get(name) is None:
                    failed += 1
                    errors.append(name)
            except Exception as e:
                failed += 1
                errors.append(f"{name}: {e}")
        return {
            "total_agents": total,
            "cached": len(self._cache),
            "tools": sum(1 for v in self._roles.values() if v == "tool"),
            "managers": sum(1 for v in self._roles.values() if v == "manager"),
            # توافق خلفي مع API القديم
            "total_registered": total,
            "failed": failed,
            "errors": errors,
            "loaded": total - failed,
        }


factory = AgentFactory()

__all__ = ["AgentFactory", "factory"]
