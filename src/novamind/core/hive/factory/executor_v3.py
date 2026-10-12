#!/usr/bin/env python3
"""
Hive Factory Executor — Professional Edition v3.0
==================================================
منفذ الوكلاء الموحد مع:
- دعم كامل لـ signature_map (تحويل ديناميكي للمعاملات).
- طبقات أمان (Security Gates).
- منطق إعادة محاولة ذكية (Exponential Backoff).
- إدارة موارد صارمة (WeakRefs + Timeouts).
- تتبع شامل (Trace IDs).
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from weakref import WeakValueDictionary

try:
    from hive.factory.registry import AgentRegistry, AgentSpec, registry
except ImportError:
    from .registry import AgentRegistry, AgentSpec, registry

logger = logging.getLogger("hive.factory.executor")


# ═══════════════════════════════════════════════════════════════
# التكوين والنتائج
# ═══════════════════════════════════════════════════════════════
@dataclass
class ExecutionConfig:
    """إعدادات سلوك التنفيذ لكل مهمة."""
    timeout_seconds: int = 30
    max_retries: int = 2
    retry_delay_base: float = 1.0
    enable_security_check: bool = True


@dataclass
class ExecutionResult:
    """الهيكل الموحد لنتيجة أي عملية تنفيذ وكيل."""
    success: bool
    agent_name: str
    output: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    attempts: int = 1
    tokens_used: int = 0
    cost_usd: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "agent_name": self.agent_name,
            "output_preview": str(self.output)[:200] if self.output else None,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
            "attempts": self.attempts,
            "tokens_used": self.tokens_used,
            "cost_usd": round(self.cost_usd, 6),
            "timestamp": self.timestamp,
            "trace_id": self.metadata.get("trace_id", "N/A"),
        }


# ═══════════════════════════════════════════════════════════════
# المنفذ الرئيسي
# ═══════════════════════════════════════════════════════════════
class AgentExecutor:
    """
    محرك تنفيذ الوكلاء المركزي.
    يدعم signature_map لفصل واجهة المستخدم عن تنفيذ الوكيل.
    """

    def __init__(
        self,
        agent_registry: Optional[AgentRegistry] = None,
        security_kernel: Optional[Any] = None
    ):
        self.registry = agent_registry or registry
        self.security_kernel = security_kernel
        self._instances: WeakValueDictionary = WeakValueDictionary()
        self._stats: Dict[str, Dict] = {}

    # ───────────────────────────────────────────────────────────
    # تحميل الوكيل
    # ───────────────────────────────────────────────────────────
    async def _get_or_load_agent(self, name: str) -> Any:
        """يدعم نمطي: class يحتاج instantiation، أو instance جاهز."""
        if name in self._instances:
            return self._instances[name]

        spec = self.registry.get(name)
        if not spec:
            raise ValueError(f"Agent '{name}' not found in registry")

        try:
            module = importlib.import_module(spec.module)
            if not hasattr(module, spec.class_name):
                raise AttributeError(
                    f"Module '{spec.module}' has no attribute '{spec.class_name}'"
                )
            obj = getattr(module, spec.class_name)

            # كشف ذكي: class أم instance؟
            if isinstance(obj, type):
                logger.debug(f"📦 '{spec.class_name}' is a class → instantiating")
                instance = obj()
            else:
                logger.debug(f"📦 '{spec.class_name}' is an instance → using directly")
                instance = obj

            self._instances[name] = instance
            logger.debug(f"✅ Loaded agent: {name} (type={type(instance).__name__})")
            return instance
        except Exception as e:
            logger.error(f"❌ Failed to load agent '{name}': {e}")
            raise

    # ───────────────────────────────────────────────────────────
    # 🎯 جوهر الحل: بناء المعاملات باستخدام signature_map
    # ───────────────────────────────────────────────────────────
    def _prepare_kwargs(
        self,
        task: str,
        ctx: Dict[str, Any],
        signature_map: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        يحول المعاملات القياسية (task, ctx) إلى ما تتوقعه دالة الوكيل الفعلية.

        يدعم ثلاثة أنواع من المفاتيح في signature_map:
        - "task"           → يُترجم إلى اسم معامل يستقبل قيمة task
        - "ctx"            → يُترجم إلى اسم معامل يستقبل ctx كاملاً
        - "ctx.<key>"      → يُترجم إلى اسم معامل يستقبل ctx["<key>"]

        مثال:
            signature_map = {"task": "code", "ctx.filename": "filename"}
            task = "def hello(): return 1"
            ctx = {"filename": "test.py", "user": "ahmed"}

            نتيجة: {"code": "def hello(): return 1", "filename": "test.py"}
        """
        # حالة 1: لا خريطة → مرر task و ctx كما هما
        if not signature_map:
            return {"task": task, "ctx": ctx}

        # حالة 2: هناك خريطة → ترجم
        mapped_args = {}
        for generic_key, actual_param_name in signature_map.items():
            if generic_key == "task":
                mapped_args[actual_param_name] = task
            elif generic_key == "ctx":
                mapped_args[actual_param_name] = ctx
            elif generic_key.startswith("ctx."):
                # استخرج المفتاح الفرعي من ctx
                ctx_key = generic_key[4:]  # إزالة "ctx."
                if ctx_key in ctx:
                    mapped_args[actual_param_name] = ctx[ctx_key]
                else:
                    logger.debug(f"⚠️ ctx['{ctx_key}'] غير موجود، تخطّي")
            # else: مفتاح غير معروف، تخطّي

        logger.debug(f"🔀 Mapped kwargs: {list(mapped_args.keys())}")
        return mapped_args

    # ───────────────────────────────────────────────────────────
    # استدعاء الطريقة
    # ───────────────────────────────────────────────────────────
    async def _invoke_method(
        self,
        agent: Any,
        method_name: str,
        task: str,
        ctx: Dict[str, Any],
        timeout: int,
        signature_map: Optional[Dict[str, str]] = None,
    ) -> Any:
        """يستدعي الدالة مع دعم sync/async و signature_map."""
        method = getattr(agent, method_name, None)

        if not method:
            for alt in ["run", "handle", "execute", "__call__"]:
                method = getattr(agent, alt, None)
                if callable(method):
                    logger.warning(f"⚠️ '{method_name}' missing → using '{alt}'")
                    break
            if not method:
                raise AttributeError(f"No method found on {agent.__class__.__name__}")

        # 🎯 الجوهر: بناء kwargs بذكاء
        sig_map = signature_map or {}
        kwargs = self._prepare_kwargs(task, ctx, sig_map)

        logger.debug(f"📞 Invoking {method_name} with: {list(kwargs.keys())}")

        try:
            if asyncio.iscoroutinefunction(method):
                return await asyncio.wait_for(method(**kwargs), timeout=timeout)
            else:
                loop = asyncio.get_running_loop()
                return await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: method(**kwargs)),
                    timeout=timeout,
                )
        except asyncio.TimeoutError:
            raise
        except Exception:
            raise

    # ───────────────────────────────────────────────────────────
    # تنفيذ وكيل واحد
    # ───────────────────────────────────────────────────────────
    async def execute(
        self,
        agent_name: str,
        task: str = "",
        ctx: Optional[Dict[str, Any]] = None,
        config: Optional[ExecutionConfig] = None,
    ) -> ExecutionResult:
        cfg = config or ExecutionConfig()
        start_time = time.time()
        last_error_msg = None
        attempt_count = 0

        trace_id = str(uuid.uuid4())[:8]

        base_ctx = ctx.copy() if ctx else {}
        base_ctx.update({
            "agent_name": agent_name,
            "trace_id": trace_id,
            "execution_id": f"{agent_name}_{int(time.time()*1000)}",
            "timestamp_start": datetime.now().isoformat(),
        })

        while attempt_count < (cfg.max_retries + 1):
            attempt_count += 1
            current_ctx = base_ctx.copy()

            try:
                # 1. تحميل الوكيل
                agent = await self._get_or_load_agent(agent_name)

                # 2. بوابة الأمان
                if cfg.enable_security_check and self.security_kernel:
                    is_safe, sanitized_ctx, violations = await self.security_kernel.check_input(
                        agent_name, task, current_ctx
                    )
                    if not is_safe:
                        logger.warning(f"🛑 Security Block: {violations}")
                        return ExecutionResult(
                            success=False,
                            agent_name=agent_name,
                            error=f"Security Violation: {'; '.join(violations)}",
                            duration_ms=(time.time() - start_time) * 1000,
                            attempts=attempt_count,
                            metadata={"trace_id": trace_id},
                        )
                    current_ctx = sanitized_ctx

                # 3. جلب المواصفات
                spec = self.registry.get(agent_name)
                target_method = spec.method if spec else "run"
                sig_map = spec.signature_map if spec else {}

                # 4. التنفيذ
                output = await self._invoke_method(
                    agent, target_method, task, current_ctx,
                    cfg.timeout_seconds, signature_map=sig_map,
                )

                duration_ms = (time.time() - start_time) * 1000
                self._record_stats(agent_name, True, duration_ms)

                return ExecutionResult(
                    success=True,
                    agent_name=agent_name,
                    output=output,
                    duration_ms=duration_ms,
                    attempts=attempt_count,
                    metadata={"trace_id": trace_id},
                )

            except asyncio.TimeoutError:
                last_error_msg = f"Timeout after {cfg.timeout_seconds}s"
                logger.warning(f"⏳ Attempt {attempt_count}/{cfg.max_retries+1} timeout")
            except Exception as e:
                last_error_msg = f"{type(e).__name__}: {str(e)}"
                logger.error(f"💥 Attempt {attempt_count}/{cfg.max_retries+1}: {last_error_msg}")

            if attempt_count <= cfg.max_retries:
                delay = cfg.retry_delay_base * (2 ** (attempt_count - 1))
                await asyncio.sleep(delay)

        duration_ms = (time.time() - start_time) * 1000
        self._record_stats(agent_name, False, duration_ms)
        return ExecutionResult(
            success=False,
            agent_name=agent_name,
            error=last_error_msg or "Unknown failure",
            duration_ms=duration_ms,
            attempts=attempt_count,
            metadata={"trace_id": trace_id},
        )

    # ───────────────────────────────────────────────────────────
    # تنفيذ سلسلة (Pipeline)
    # ───────────────────────────────────────────────────────────
    async def execute_pipeline(
        self,
        pipeline: List[Dict[str, Any]],
        initial_ctx: Optional[Dict[str, Any]] = None,
    ) -> List[ExecutionResult]:
        results = []
        ctx = initial_ctx or {}
        for i, step in enumerate(pipeline):
            agent_name = step.get("agent")
            task = step.get("task", "")
            if not agent_name:
                break
            if results and not results[-1].success:
                break
            if results:
                ctx["previous_output"] = results[-1].output
            result = await self.execute(agent_name, task, ctx)
            results.append(result)
        return results

    # ───────────────────────────────────────────────────────────
    # إحصائيات
    # ───────────────────────────────────────────────────────────
    def _record_stats(self, agent_name: str, success: bool, duration_ms: float):
        if agent_name not in self._stats:
            self._stats[agent_name] = {
                "total_calls": 0, "successful_calls": 0, "failed_calls": 0,
                "total_duration_ms": 0.0, "avg_duration_ms": 0.0,
            }
        s = self._stats[agent_name]
        s["total_calls"] += 1
        if success: s["successful_calls"] += 1
        else: s["failed_calls"] += 1
        s["total_duration_ms"] += duration_ms
        s["avg_duration_ms"] = s["total_duration_ms"] / s["total_calls"]

    def print_report(self):
        print("\n" + "=" * 70)
        print("📊 AGENT EXECUTION PERFORMANCE REPORT")
        print("=" * 70)
        if not self._stats:
            print("   No statistics recorded yet.")
            return
        print(f"{'Agent Name':<25} | {'Calls':>5} | {'Success%':>8} | {'Avg Time(ms)':>12}")
        print("-" * 70)
        for name, s in sorted(self._stats.items(), key=lambda x: -x[1]["total_duration_ms"]):
            rate = (s["successful_calls"] / s["total_calls"] * 100) if s["total_calls"] else 0
            icon = "✅" if rate >= 90 else ("⚠️" if rate >= 70 else "❌")
            print(f"{icon} {name:<23} | {s['total_calls']:>5} | {rate:>7.1f}% | {s['avg_duration_ms']:>11.1f}ms")
        print("=" * 70)


# ═══════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════
executor = AgentExecutor(security_kernel=None)

