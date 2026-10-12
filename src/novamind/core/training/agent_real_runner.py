"""
AgentRealTestRunner — يربط الاختبارات الحقيقية بالوكلاء الحقيقيين
اكتشاف ذكي للطرق المتاحة
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Callable, Any
import time
import logging
import inspect

from .real_evaluator import RealEvaluator, RealEvaluationReport
from .agent_adapters import get_adapter

logger = logging.getLogger("agent_real_runner")


class AgentRealTestRunner:
    """
    يشغّل الاختبارات الحقيقية على وكيل حقيقي
    يكتشف تلقائياً كيف يستدعي الوكيل
    """
    
    # أولويات الدوال المحتملة
    METHOD_CANDIDATES = [
        "generate",
        "run",
        "process",
        "execute",
        "call",
        "invoke",
        "handle",
        "analyze",
        "generate_code",
        "generate_text",
        "__call__",
    ]
    
    def __init__(self, evaluator: Optional[RealEvaluator] = None):
        self.evaluator = evaluator or RealEvaluator()
        self.history: List[Dict] = []
        self._method_cache: Dict[str, str] = {}
    
    def discover_method(self, agent_instance) -> Optional[str]:
        """اكتشف الطريقة الأنسب لاستدعاء الوكيل"""
        agent_class = type(agent_instance).__name__
        
        # cache
        if agent_class in self._method_cache:
            return self._method_cache[agent_class]
        
        # جرّب الطرق بالترتيب
        for method_name in self.METHOD_CANDIDATES:
            if hasattr(agent_instance, method_name):
                attr = getattr(agent_instance, method_name)
                if callable(attr):
                    # تحقق من التوقيع
                    try:
                        sig = inspect.signature(attr)
                        params = list(sig.parameters.keys())
                        # يجب أن يقبل معاملاً واحداً على الأقل
                        # (بعد self إن كان method)
                        non_self = [p for p in params if p != "self"]
                        if len(non_self) >= 1:
                            logger.info(f"  Discovered method: {agent_class}.{method_name}")
                            self._method_cache[agent_class] = method_name
                            return method_name
                    except (ValueError, TypeError):
                        continue
        
        # إذا لم نجد، اطبع ما هو متاح
        logger.warning(f"  No known method found on {agent_class}")
        logger.warning(f"  Available methods:")
        for name in dir(agent_instance):
            if not name.startswith("_"):
                attr = getattr(agent_instance, name)
                if callable(attr):
                    logger.warning(f"    - {name}")
        
        return None
    
    def build_agent_fn(self, agent_instance, method: Optional[str] = None, spec: str = "") -> Callable:
        """ابنِ دالة agent_fn من instance الوكيل"""
        # استخدم adapter إذا كان spec معروفاً
        if spec:
            logger.info(f"Using adapter for spec={spec}")
            return get_adapter(spec, agent_instance)
        
        # وإلا اكتشاف تلقائي
        if method is None:
            method = self.discover_method(agent_instance)
        
        if method is None:
            def failed_agent_fn(prompt: str) -> str:
                return f"ERROR: No method found on {type(agent_instance).__name__}"
            return failed_agent_fn
        
        def agent_fn(prompt: str) -> str:
            try:
                fn = getattr(agent_instance, method)
                try:
                    result = fn(prompt)
                except TypeError:
                    try:
                        result = fn(prompt=prompt)
                    except TypeError:
                        result = fn({"prompt": prompt})
                return self._extract_text(result)
            except Exception as e:
                logger.error(f"Agent call failed: {e}")
                return f"ERROR: {e}"
        
        return agent_fn
    
    def _extract_text(self, result: Any) -> str:
        """استخرج النص من النتيجة مهما كان نوعها"""
        if result is None:
            return ""
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            for key in ["text", "content", "output", "result", "response", "code", "message"]:
                if key in result and isinstance(result[key], str):
                    return result[key]
            # إذا لم نجد، اجمع كل القيم
            return str(result)
        if hasattr(result, "text"):
            return result.text or ""
        if hasattr(result, "content"):
            return result.content or ""
        return str(result)
    
    def run_tests(
        self,
        agent_id: str,
        spec: str,
        agent_instance: Any,
        method: Optional[str] = None,
    ) -> RealEvaluationReport:
        """شغّل الاختبارات الحقيقية على وكيل حقيقي"""
        logger.info(f"Running real tests on {agent_id} ({spec})")
        
        agent_fn = self.build_agent_fn(agent_instance, method, spec=spec)
        report = self.evaluator.evaluate(agent_id, spec, agent_fn)
        
        self.history.append({
            "agent_id": agent_id,
            "spec": spec,
            "verdict": report.verdict,
            "score": report.total_score,
            "at": time.time(),
        })
        
        return report
    
    def stats(self) -> Dict:
        if not self.history:
            return {"total": 0}
        return {
            "total": len(self.history),
            "passed": sum(1 for r in self.history if r["verdict"] == "passed"),
            "failed": sum(1 for r in self.history if r["verdict"] == "failed"),
            "avg_score": round(
                sum(r["score"] for r in self.history) / len(self.history), 3
            ),
        }
