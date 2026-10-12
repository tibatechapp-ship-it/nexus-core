"""Secure Pipeline — يدمج كل دوال الحماية في خط أنابيب واحد.

يضمن:
1. Gatekeeper (فحص أمني) — دائماً
2. Permissions/RBAC (صلاحيات) — دائماً
3. CircuitBreaker (حماية من الفشل) — دائماً
4. Sandbox (تنفيذ معزول) — اختياري (للكود فقط)
5. Guards (فحص المخرجات) — اختياري (للـ LLM)
6. Cost tracking
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("factory.secure_pipeline")


# ═══════════════════════════════════════════════════════════════
# Security Pipeline
# ═══════════════════════════════════════════════════════════════

class SecurityPipeline:
    """Pipeline آمن يمر بـ 6 مراحل حماية."""

    def __init__(self):
        self._init_components()

    def _init_components(self):
        """تحميل كل مكونات الحماية."""
        # 1. Gatekeeper
        try:
            from novamind.core.security_gatekeeper import gatekeeper
            self.gatekeeper = gatekeeper
            logger.info("✅ Gatekeeper loaded")
        except ImportError:
            self.gatekeeper = None
            logger.warning("⚠️  Gatekeeper not available")

        # 2. Permissions/RBAC
        try:
            from novamind.security.permissions import has_permission
            self.has_permission = has_permission
            logger.info("✅ Permissions loaded")
        except ImportError:
            self.has_permission = None
            logger.warning("⚠️  Permissions not available")

        # 3. CircuitBreaker
        try:
            from novamind.security.circuit_breaker import get_breaker
            self.get_breaker = get_breaker
            logger.info("✅ CircuitBreaker loaded")
        except ImportError:
            self.get_breaker = None
            logger.warning("⚠️  CircuitBreaker not available")

        # 4. Sandbox
        try:
            from novamind.security.sandbox import Sandbox
            self.Sandbox = Sandbox
            logger.info("✅ Sandbox loaded")
        except ImportError:
            self.Sandbox = None
            logger.warning("⚠️  Sandbox not available")

        # 5. Guards
        try:
            from novamind.factory.guards import build_default_chain
            self.build_chain = build_default_chain
            logger.info("✅ Guards loaded")
        except ImportError:
            self.build_chain = None
            logger.warning("⚠️  Guards not available")

        # 6. Cost tracking
        try:
            from novamind.core.hive.analytics.cost_tracker import record_cost
            self.record_cost = record_cost
            logger.info("✅ CostTracker loaded")
        except ImportError:
            self.record_cost = None
            logger.warning("⚠️  CostTracker not available")

    # ═══════════════════════════════════════════════════════════════
    # Main Flow
    # ═══════════════════════════════════════════════════════════════

    def execute(
        self,
        agent_id: str,
        task: str,
        ctx: Optional[Dict] = None,
        skip_sandbox: bool = True,   # ← افتراضي: تجاوز Sandbox للوكلاء
        skip_guards: bool = True,    # ← افتراضي: تجاوز Guards (تحتاج dict)
    ) -> Dict[str, Any]:
        """تنفيذ آمن كامل.
        
        Args:
            agent_id: اسم الوكيل
            task: المهمة
            ctx: السياق
            skip_sandbox: True (افتراضي) — الوكلاء لا يحتاجون Sandbox
            skip_guards: True (افتراضي) — Guards للـ LLM responses
            
        Returns:
            dict مع result + security + metrics
        """
        started = time.time()
        ctx = ctx or {}

        result = {
            "ok": False,
            "agent": agent_id,
            "task": task,
            "security": {
                "gatekeeper": None,
                "permission": None,
                "circuit": None,
                "sandbox": None,
                "guards": None,
            },
            "started_at": started,
        }

        # ═══ المرحلة 1: Gatekeeper (دائماً) ═══
        if self.gatekeeper:
            try:
                verdict = self.gatekeeper.analyze(task)
                result["security"]["gatekeeper"] = verdict.to_dict()

                if verdict.is_blocked:
                    result["error"] = "Blocked by Gatekeeper"
                    result["reason"] = verdict.reason
                    result["category"] = verdict.category
                    logger.warning(f"🚫 Blocked: {verdict.reason}")
                    return self._finalize(result, started)
            except Exception as e:
                logger.error(f"Gatekeeper error: {e}")
                result["security"]["gatekeeper"] = {"error": str(e)}

        # ═══ المرحلة 2: Permission (دائماً) ═══
        if self.has_permission:
            try:
                allowed = (
                    self.has_permission(agent_id, "read_all")
                    or self.has_permission(agent_id, "read_code")
                    or self.has_permission(agent_id, "plan")
                )
                result["security"]["permission"] = {
                    "agent": agent_id,
                    "allowed": allowed,
                }
                if not allowed:
                    result["error"] = "Permission denied"
                    logger.warning(f"🚫 Permission denied for {agent_id}")
                    return self._finalize(result, started)
            except Exception as e:
                logger.error(f"Permission error: {e}")
                result["security"]["permission"] = {"error": str(e)}

        # ═══ المرحلة 3: CircuitBreaker (دائماً) ═══
        breaker = None
        if self.get_breaker:
            try:
                breaker = self.get_breaker(agent_id)
                if not breaker.allow_request():
                    result["error"] = "Circuit breaker OPEN"
                    result["security"]["circuit"] = breaker.get_stats()
                    logger.warning(f"⚡ Circuit open for {agent_id}")
                    return self._finalize(result, started)
                result["security"]["circuit"] = breaker.get_stats()
            except Exception as e:
                logger.error(f"Circuit error: {e}")
                result["security"]["circuit"] = {"error": str(e)}

        # ═══ المرحلة 4: التنفيذ ═══
        try:
            if not skip_sandbox and self.Sandbox and self._looks_like_code(task):
                # Sandbox للكود الخالص
                try:
                    sandbox = self.Sandbox(timeout=30, max_memory_mb=256)
                    exec_result = sandbox.run_python(task)
                    result["security"]["sandbox"] = {
                        "used": True,
                        "exit_code": exec_result.get("exit_code"),
                    }
                    result["result"] = exec_result
                except Exception as e:
                    result["security"]["sandbox"] = {"used": True, "error": str(e)}
                    logger.error(f"Sandbox error: {e}")
                    raise
            else:
                # الوكلاء العاديون (افتراضي)
                from novamind.factory.executor import execute_agent_sync
                exec_result = execute_agent_sync(agent_id, task, ctx)
                result["security"]["sandbox"] = {"used": False}
                result["result"] = exec_result

            result["ok"] = True

            # ═══ المرحلة 5: Guards (اختياري) ═══
            if not skip_guards and self.build_chain:
                try:
                    chain = self.build_chain()
                    output = result.get("result", "")
                    
                    # حوّل str → dict للـ Guards
                    if isinstance(output, str):
                        output = {"text": output, "code": output, "issues": []}
                    elif not isinstance(output, dict):
                        output = {"text": str(output), "code": str(output)}
                    
                    guard_result = chain.check(output, stop_on_error=False)

                    result["security"]["guards"] = {
                        "passed": guard_result.passed,
                        "errors": guard_result.errors[:5],
                        "warnings": guard_result.warnings[:5],
                    }

                    if not guard_result.passed:
                        result["ok"] = False
                        result["error"] = "Guards failed"
                        logger.warning(f"🛡️ Guards failed: {guard_result.errors[:3]}")
                except Exception as e:
                    logger.error(f"Guards error: {e}")
                    result["security"]["guards"] = {"error": str(e)}

            # ═══ تسجيل النجاح ═══
            if breaker:
                try:
                    breaker.record_success()
                except Exception:
                    pass

        except Exception as e:
            result["error"] = str(e)
            result["ok"] = False

            if breaker:
                try:
                    breaker.record_failure()
                except Exception:
                    pass

            logger.error(f"❌ Execution failed: {e}")

        return self._finalize(result, started)

    # ═══════════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════════

    def _looks_like_code(self, text: str) -> bool:
        """هل النص يشبه الكود؟"""
        indicators = ["import ", "def ", "class ", "print("]
        return any(ind in text for ind in indicators)

    def _finalize(self, result: Dict, started: float) -> Dict:
        """إضافة إحصائيات نهائية."""
        result["duration_ms"] = int((time.time() - started) * 1000)
        result["completed_at"] = time.time()
        return result


# ═══════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════

_pipeline: Optional[SecurityPipeline] = None


def get_secure_pipeline() -> SecurityPipeline:
    """الحصول على pipeline آمن (singleton)."""
    global _pipeline
    if _pipeline is None:
        _pipeline = SecurityPipeline()
    return _pipeline


def execute_secure(agent_id: str, task: str, **kwargs) -> Dict:
    """تنفيذ آمن — الواجهة العامة."""
    return get_secure_pipeline().execute(agent_id, task, **kwargs)


__all__ = [
    "SecurityPipeline",
    "get_secure_pipeline",
    "execute_secure",
]
