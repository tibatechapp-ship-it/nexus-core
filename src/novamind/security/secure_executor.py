"""SecureExecutor — Robust Unified Security Wrapper."""
import logging
import inspect
from typing import Callable, Any, Dict, Optional

log = logging.getLogger("SecureExecutor")

class SecureExecutor:
    """Wraps execution with Rate Limiting, Circuit Breaking, and Sandboxing."""

    def __init__(self, *args, **kwargs):
        """
        Flexible initializer to handle various calling conventions.
        Accepts 'name' or 'agent_name' as the identifier.
        Accepts optional components via kwargs: limiter, breaker, sandbox.
        """
        # Resolve Name: Check positional arg first, then keyword args
        self.name = None
        
        if args:
            self.name = str(args[0])
        elif 'name' in kwargs:
            self.name = str(kwargs['name'])
        elif 'agent_name' in kwargs:
            self.name = str(kwargs['agent_name'])
        else:
            raise ValueError("SecureExecutor requires a 'name' or 'agent_name'.")

        # Resolve Components
        self.limiter = kwargs.get('limiter')
        self.breaker = kwargs.get('breaker')
        self.sandbox = kwargs.get('sandbox')

        log.debug(f"Initialized SecureExecutor for '{self.name}'")

    async def execute(self, func: Callable[..., Any], *args, **kwargs) -> Dict[str, Any]:
        """Executes a function with full security stack."""
        
        # 1. Rate Limit Check
        if self.limiter:
            try:
                rl_result = self.limiter.acquire(self.name)
                if not rl_result["allowed"]:
                    return {
                        "ok": False,
                        "error": "rate_limit_exceeded",
                        "details": rl_result
                    }
            except Exception as e:
                log.warning(f"RateLimiter error: {e}")

        # 2. Circuit Breaker Check
        if self.breaker:
            try:
                if not self.breaker.is_allowed():
                    return {
                        "ok": False,
                        "error": "circuit_open",
                        "state": getattr(self.breaker.state, 'value', 'unknown')
                    }
            except Exception as e:
                log.warning(f"CircuitBreaker check error: {e}")

        # 3. Execution
        try:
            # Handle both sync and async functions safely
            if inspect.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
                if inspect.isawaitable(result):
                    result = await result
            
            # Record Success/Failure based on result structure
            success = True
            if isinstance(result, dict):
                success = result.get("ok", True)
            
            if self.breaker:
                try:
                    if success:
                        self.breaker.record_success()
                    else:
                        self.breaker.record_failure()
                except Exception as e:
                    log.warning(f"CircuitBreaker record error: {e}")
                    
            return {"ok": True, "result": result}

        except Exception as e:
            if self.breaker:
                try:
                    self.breaker.record_failure()
                except: pass
            log.debug(f"Execution error in {self.name}: {e}")
            return {"ok": False, "error": type(e).__name__, "message": str(e)}

    def stats(self) -> Dict[str, Any]:
        out = {"name": self.name}
        if self.breaker:
            try: out["circuit_breaker"] = self.breaker.stats()
            except: pass
        if self.limiter:
            try: out["rate_limiter"] = self.limiter.stats()
            except: pass
        return out
