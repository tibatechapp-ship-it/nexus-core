"""
AgentAdapters — محوّلات لكل وكيل حقيقي
تُوحّد الواجهة: كل وكيل يُستدعى بـ prompt يُرجع str
"""
from typing import Callable, Any, Dict, Optional
import logging
import inspect

logger = logging.getLogger("agent_adapters")


# ═══════════════════════════════════════════════════════
# محوّل لكل نوع وكيل
# ═══════════════════════════════════════════════════════

def coder_adapter(agent) -> Callable:
    """CoderAgent: build(request) -> {code}"""
    def fn(prompt: str) -> str:
        try:
            result = agent.build(prompt)
            if isinstance(result, dict):
                return result.get("code", "") or str(result)
            return str(result)
        except Exception as e:
            logger.error(f"CoderAgent failed: {e}")
            return f"ERROR: {e}"
    return fn


def security_adapter(agent) -> Callable:
    """SecurityAgent: analyze(code, filename) -> {findings}"""
    def fn(prompt: str) -> str:
        try:
            result = agent.analyze(prompt, "code.py")
            if isinstance(result, dict):
                # اجمع كل التقارير
                parts = []
                if "findings" in result:
                    for f in result["findings"]:
                        parts.append(str(f))
                if "issues" in result:
                    for issue in result["issues"]:
                        parts.append(str(issue))
                if "summary" in result:
                    parts.append(str(result["summary"]))
                if parts:
                    return "\n".join(parts)
                return str(result)
            return str(result)
        except Exception as e:
            logger.error(f"SecurityAgent failed: {e}")
            return f"ERROR: {e}"
    return fn


def analyzer_adapter(agent) -> Callable:
    """AnalyzerAgent: analyze(code, filename) -> {analysis}"""
    def fn(prompt: str) -> str:
        try:
            result = agent.analyze(prompt, "code.py")
            if isinstance(result, dict):
                parts = []
                for key in ["issues", "bugs", "summary", "analysis", "recommendations"]:
                    if key in result:
                        val = result[key]
                        if isinstance(val, list):
                            parts.extend(str(v) for v in val)
                        else:
                            parts.append(str(val))
                if parts:
                    return "\n".join(parts)
                return str(result)
            return str(result)
        except Exception as e:
            logger.error(f"AnalyzerAgent failed: {e}")
            return f"ERROR: {e}"
    return fn


def fixer_adapter(agent) -> Callable:
    """FixerAgent: fix(code, error, issues) -> {code}"""
    def fn(prompt: str) -> str:
        try:
            result = agent.fix(prompt, "", [])
            if isinstance(result, dict):
                return result.get("code", "") or result.get("fixed", "") or str(result)
            return str(result)
        except Exception as e:
            logger.error(f"FixerAgent failed: {e}")
            return f"ERROR: {e}"
    return fn


def tester_adapter(agent) -> Callable:
    """Tester: run(...) -> ?"""
    def fn(prompt: str) -> str:
        try:
            # جرّب استدعاءات مختلفة
            try:
                result = agent.run(prompt)
            except TypeError:
                try:
                    result = agent.run(code=prompt)
                except TypeError:
                    result = agent.run({"code": prompt})
            if isinstance(result, dict):
                return str(result.get("stdout", "")) or str(result)
            return str(result)
        except Exception as e:
            logger.error(f"Tester failed: {e}")
            return f"ERROR: {e}"
    return fn


def learner_adapter(agent) -> Callable:
    """LearnerAgent: learn(...) -> ?"""
    def fn(prompt: str) -> str:
        try:
            try:
                result = agent.learn(prompt)
            except TypeError:
                try:
                    result = agent.learn({"text": prompt})
                except TypeError:
                    result = agent.learn(text=prompt)
            return str(result)
        except Exception as e:
            logger.error(f"LearnerAgent failed: {e}")
            return f"ERROR: {e}"
    return fn


# ═══════════════════════════════════════════════════════
# سجل المحوّلات
# ═══════════════════════════════════════════════════════

ADAPTER_REGISTRY: Dict[str, Callable] = {
    "coder": coder_adapter,
    "security": security_adapter,
    "analyzer": analyzer_adapter,
    "fixer": fixer_adapter,
    "tester": tester_adapter,
    "learner": learner_adapter,
}


def get_adapter(spec: str, agent_instance) -> Callable:
    """
    احصل على محوّل مناسب لوكيل
    
    - إذا كان في السجل، استخدمه
    - وإلا، اكتشف تلقائياً
    """
    # 1. جرّب السجل أولاً
    if spec in ADAPTER_REGISTRY:
        return ADAPTER_REGISTRY[spec](agent_instance)
    
    # 2. اكتشاف تلقائي
    logger.info(f"No adapter for '{spec}', auto-discovering...")
    return _auto_discover_adapter(agent_instance)


def _auto_discover_adapter(agent) -> Callable:
    """اكتشف تلقائياً كيف تستدعي الوكيل"""
    # ابحث عن أي method يستقبل str ويعيد str/dict
    candidate_methods = [
        "generate", "run", "process", "execute", "call",
        "build", "fix", "analyze", "learn", "test",
    ]
    
    for method_name in candidate_methods:
        if not hasattr(agent, method_name):
            continue
        
        method = getattr(agent, method_name)
        if not callable(method):
            continue
        
        # جرّبها
        def fn(prompt: str, _method=method) -> str:
            try:
                result = _method(prompt)
                if isinstance(result, dict):
                    # ابحث عن أي قيمة نصية
                    for v in result.values():
                        if isinstance(v, str) and len(v) > 10:
                            return v
                    return str(result)
                return str(result)
            except TypeError:
                # جرّب kwargs
                try:
                    result = _method(prompt=prompt)
                    return str(result)
                except Exception:
                    pass
                return f"ERROR: can't call {method_name}"
            except Exception as e:
                return f"ERROR: {e}"
        
        return fn
    
    # لم نجد شيئاً
    def fallback(prompt: str) -> str:
        return f"ERROR: no method on {type(agent).__name__}"
    
    return fallback
