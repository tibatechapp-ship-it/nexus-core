"""Supervisor — ينفذ قرار SmartRouter."""
from __future__ import annotations
import os
import sys
import time
import concurrent.futures
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from src.orchestrator.smart_router import SmartRouter


class Supervisor:
    """يشرف على تنفيذ المهام بفريق من الوكلاء."""

    # ═══ كشف الطرق (30+) ═══
    METHOD_CANDIDATES = [
        "build", "run", "execute", "analyze", "fix", "review",
        "generate", "process", "handle", "cleanup", "check",
        "scan", "audit", "validate", "improve", "test",
        "review_code", "optimize", "format", "migrate",
        "deploy", "monitor", "report", "learn", "train",
        "navigate", "search", "index", "parse", "refactor",
        "detect", "inspect", "lint", "verify",
    ]

    def __init__(self, use_rag: bool = True, verbose: bool = True) -> None:
        self.router = SmartRouter()
        self.use_rag = use_rag
        self.verbose = verbose
        self._rag: Any = None
        self._registry: Any = None

    def _get_registry(self) -> Any:
        if self._registry is None:
            from nova.registry import REGISTRY  # type: ignore[import-not-found]
            self._registry = REGISTRY
        return self._registry

    def _get_rag(self) -> Any:
        if self._rag is None and self.use_rag:
            try:
                from src.memory.agent_rag_bridge import get_bridge
                self._rag = get_bridge()
            except Exception:
                self._rag = None
        return self._rag

    def _detect_method(self, agent: Any) -> str | None:
        """يكتشف الطريقة المتاحة."""
        for m in self.METHOD_CANDIDATES:
            if hasattr(agent, m) and callable(getattr(agent, m)):
                return m
        return None

    def _run_single(self, agent_name: str, prompt: str) -> dict:
        """يشغّل وكيلاً واحداً (يدعم sync + async) مع cache."""
        import asyncio
        import inspect

        # ═══ CACHE GET ═══
        if self.use_cache:
            try:
                from src.orchestrator.agent_cache import get as cache_get
                cache_prompt = f"[result-contract:v2] {prompt}"
                cached = cache_get(agent_name, cache_prompt)
                if cached:
                    return {
                        "ok": True, "status": "cached_success", "agent": agent_name,
                        "method": "cached", "result": cached, "elapsed": 0.01,
                    }
            except Exception:
                pass

        start = time.time()
        try:
            agent = self._get_registry().load_agent(agent_name)
        except Exception as e:
            return {"ok": False, "agent": agent_name, "error": f"تحميل: {e}",
                    "elapsed": 0.0}

        method = self._detect_method(agent)
        if not method:
            available = [m for m in dir(agent)
                        if not m.startswith("_") and callable(getattr(agent, m, None))]
            return {"ok": False, "agent": agent_name,
                    "error": f"لا طريقة. المتاح: {available[:5]}", "elapsed": 0.0}

        fn = getattr(agent, method)
        result = None
        last_error = None

        # ═══ dict غني بكل المفاتيح المحتملة ═══
        rich_dict = {
            "action": "plan",
            "params": {
                "request": prompt,
                "content": prompt,
                "input": prompt,
                "task": prompt,
                "prompt": prompt,
            },
            "task": prompt,
            "prompt": prompt,
            "input": prompt,
            "request": prompt,
            "content": prompt,
        }

        # ═══ محاولات متعددة (4 أنماط) ═══
        ATTEMPTS = [
            lambda f: f(prompt),                # (str) — الأكثر شيوعاً
            lambda f: f(rich_dict),             # (dict) — مع كل المفاتيح
            lambda f: f(prompt, {}),            # (str, dict)
            lambda f: f(),                      # ()
        ]

        for i, attempt in enumerate(ATTEMPTS):
            try:
                if inspect.iscoroutinefunction(fn):
                    result = asyncio.run(attempt(fn))
                else:
                    result = attempt(fn)
                break  # نجح — أوقف المحاولات
            except (TypeError, AttributeError, KeyError) as e:
                # فشل النمط — جرّب التالي
                last_error = e
                continue
            except Exception as e:
                # خطأ آخر (ValueError, RuntimeError...)
                return {"ok": False, "agent": agent_name, "error": str(e),
                        "elapsed": round(time.time() - start, 3)}

        if result is None:
            return {"ok": False, "agent": agent_name,
                    "error": f"كل الأنماط فشلت: {last_error}",
                    "elapsed": round(time.time() - start, 3)}

        # ═══ إذا كانت النتيجة coroutine لم تُنتظر ═══
        if inspect.iscoroutine(result):
            try:
                result = asyncio.run(result)
            except Exception as e:
                return {"ok": False, "agent": agent_name, "error": str(e),
                        "elapsed": round(time.time() - start, 3)}

        # A returned object is not automatically a successful execution.
        if isinstance(result, dict):
            provider = str(result.get("provider", "")).strip().lower()
            status = str(result.get("status", "")).strip().lower()
            output_text = str(result.get("text") or result.get("answer") or result.get("result") or "")
            simulated = (
                bool(result.get("simulated"))
                or provider in {"mock", "mock-provider", "offline"}
                or output_text.lstrip().lower().startswith(("[mock]", "[simulation only]", "mock:"))
            )
            explicit_failure = (
                result.get("ok") is False
                or result.get("success") is False
                or bool(result.get("error"))
                or status in {"failed", "error", "llm_unavailable", "llm_provider_error"}
            )
            flags = [result[key] for key in ("ok", "success") if key in result]
            reported_success = all(flag is True for flag in flags) if flags else bool(result)
            if simulated or explicit_failure or not reported_success:
                result_str = str(result)[:2000]
                reason = (
                    "simulated result rejected" if simulated
                    else str(result.get("error") or status or "agent reported failure")[:300]
                )
                return {
                    "ok": False,
                    "status": "simulated_result_rejected" if simulated else "agent_reported_failure",
                    "agent": agent_name,
                    "method": method,
                    "error": reason,
                    "result": result_str,
                    "elapsed": round(time.time() - start, 3),
                }
            result_str = str(result)[:2000]
        else:
            if result is None or not str(result).strip():
                return {
                    "ok": False, "status": "empty_agent_result", "agent": agent_name,
                    "method": method, "error": "Agent returned no result",
                    "elapsed": round(time.time() - start, 3),
                }
            result_str = str(result)[:2000]
            if result_str.lstrip().lower().startswith(("[mock]", "[simulation only]", "mock:")):
                return {
                    "ok": False, "status": "simulated_result_rejected", "agent": agent_name,
                    "method": method, "error": "simulated result rejected",
                    "result": result_str,
                    "elapsed": round(time.time() - start, 3),
                }

        # Cache only validated successes, under a versioned contract key.
        if self.use_cache:
            try:
                from src.orchestrator.agent_cache import set as cache_set
                cache_set(agent_name, f"[result-contract:v2] {prompt}", result_str)
            except Exception:
                pass

        return {
            "ok": True,
            "status": "success",
            "agent": agent_name,
            "method": method,
            "result": result_str,
            "elapsed": round(time.time() - start, 3),
        }

    def execute(self, prompt: str, force_strategy: str | None = None) -> dict:
        """ينفذ المهمة."""
        decision = self.router.decide(prompt)
        if force_strategy:
            decision.strategy = force_strategy

        if self.verbose:
            self._print_decision(decision)

        # RAG
        working_prompt = prompt
        if self.use_rag:
            rag = self._get_rag()
            if rag:
                try:
                    docs = rag.recall(prompt, k=3)
                    if docs:
                        if self.verbose:
                            print(f"🧠 RAG: {len(docs)} وثيقة مسترجعة")
                        ctx = "\n".join(f"  • [{d.id}] {d.text[:100]}" for d in docs)
                        working_prompt = f"{prompt}\n\n━━━ سياق ━━━\n{ctx}"
                except Exception:
                    pass

        # التنفيذ حسب الاستراتيجية
        start_total = time.time()
        results = []

        if decision.strategy == "single":
            if self.verbose:
                print(f"🚀 تشغيل: {decision.agents[0]}\n")
            results.append(self._run_single(decision.agents[0], working_prompt))

        elif decision.strategy == "sequential":
            if self.verbose:
                print(f"🔄 تنفيذ متسلسل ({len(decision.agents)} وكلاء)\n")
            current_input = working_prompt
            for i, agent_name in enumerate(decision.agents, 1):
                if self.verbose:
                    print(f"  ▶️  [{i}/{len(decision.agents)}] {agent_name}")
                r = self._run_single(agent_name, current_input)
                results.append(r)
                if not r.get("ok"):
                    break
                if i < len(decision.agents):
                    current_input = f"{prompt}\n\n---\nنتيجة {agent_name}:\n{r['result'][:500]}"

        elif decision.strategy == "parallel":
            if self.verbose:
                print(f"⚡ تنفيذ متوازي ({len(decision.agents)} وكلاء)\n")
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
                futures = {ex.submit(self._run_single, a, working_prompt): a
                           for a in decision.agents}
                for future in concurrent.futures.as_completed(futures):
                    a = futures[future]
                    try:
                        r = future.result(timeout=60)
                        results.append(r)
                        if self.verbose:
                            s = "✅" if r.get("ok") else "❌"
                            print(f"  {s} {a} ({r.get('elapsed', 0)}ث)")
                    except Exception as e:
                        results.append({"ok": False, "agent": a, "error": str(e)})

        elif decision.strategy == "council":
            if self.verbose:
                print(f"🏛️  تحويل للمجلس (خطورة: {decision.risk_level})\n")
            try:
                from src.council.rag_bridge import get_council_bridge
                council = get_council_bridge()
                cr = council.deliberate_with_memory(prompt)
                execution_ok = bool(getattr(cr, "execution_ok", True))
                verdict = str(getattr(cr, "verdict", "human_review"))
                decision_approved = execution_ok and verdict == "approve"
                if not execution_ok:
                    council_status = "execution_failed"
                elif verdict == "reject":
                    council_status = "decision_rejected"
                elif verdict == "human_review":
                    council_status = "human_review"
                else:
                    council_status = "success"
                results.append({
                    "ok": decision_approved,
                    "status": council_status,
                    "agent": "council",
                    "verdict": verdict,
                    "score": cr.score,
                    "rounds": cr.rounds,
                    "errors": list(getattr(cr, "errors", [])),
                    "result": f"Council: {verdict} (score={cr.score:.2f})",
                })
            except Exception as e:
                results.append({"ok": False, "agent": "council", "error": str(e)})

        elapsed_total = time.time() - start_total

        # حفظ النتيجة في الذاكرة
        all_succeeded = bool(results) and all(r.get("ok") is True for r in results)
        any_succeeded = any(r.get("ok") is True for r in results)
        if self.use_rag and all_succeeded:
            rag = self._get_rag()
            if rag:
                try:
                    rag.remember(f"[{decision.strategy}/{decision.category}] {prompt[:100]}")
                except Exception:
                    pass

        return {
            "ok": all_succeeded,
            "status": "success" if all_succeeded else ("partial" if any_succeeded else "failed"),
            "partial": any_succeeded and not all_succeeded,
            "decision": {
                "strategy": decision.strategy,
                "category": decision.category,
                "complexity": decision.complexity,
                "risk": decision.risk_level,
                "agents": decision.agents,
                "reason": decision.reason,
            },
            "results": results,
            "elapsed": round(elapsed_total, 3),
        }

    def _print_decision(self, d: Any) -> None:
        print(f"\n{'='*60}")
        print("🧠 Smart Router — القرار")
        print(f"{'='*60}")
        print(f"   📁 الفئة:        {d.category}")
        print(f"   📊 التعقيد:      {d.complexity}")
        print(f"   ⚠️  الخطورة:      {d.risk_level}")
        print(f"   🎯 الاستراتيجية: {d.strategy}")
        print(f"   👥 الأعضاء:      {', '.join(d.agents)}")
        print(f"   💡 السبب:        {d.reason}")
        print(f"   ⏱️  متوقع:        {d.estimated_time:.1f}ث")
        print(f"{'='*60}\n")
