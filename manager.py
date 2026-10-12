"""
HookManager - Extensible event system
- Register hooks by name with priority
- Trigger all handlers for an event
- Timeout protection (a slow hook never blocks the loop)
- Error isolation (one failing hook does not stop others)
- Context allows cancel/modify
"""
import asyncio
import inspect
import logging
from typing import Callable, Dict, List, Any, Optional

logger = logging.getLogger("hooks")

# Hook event names
HOOK_NAMES = {
    "session:start",
    "session:end",
    "tool:before",
    "tool:after",
    "tool:error",
    "fix:success",
    "fix:failed",
    "memory:recall",
    "memory:remember",
    "file:before_write",
    "file:changed",
    "agent:error",
}


class HookContext:
    """Context passed to each hook handler"""

    def __init__(self, name: str, data: Dict[str, Any]):
        self.name = name
        self.data = dict(data)
        self.cancelled = False
        self.modified = False

    def cancel(self, reason: str = "") -> None:
        """Cancel the current operation"""
        self.cancelled = True
        if reason:
            logger.warning("[hooks] " + self.name + " cancelled: " + reason)

    def modify(self, patch: Dict[str, Any]) -> None:
        """Modify the data passed to subsequent hooks"""
        self.data.update(patch)
        self.modified = True


class RegisteredHook:
    def __init__(self, handler, priority: int, timeout: float, once: bool):
        self.handler = handler
        self.priority = priority
        self.timeout = timeout
        self.once = once
        self.fires = 0


class HookManager:
    def __init__(self):
        self._hooks: Dict[str, List[RegisteredHook]] = {}

    def register(self, name: str, handler: Callable, priority: int = 100,
                 timeout: float = 5.0, once: bool = False) -> None:
        """Registers a hook handler"""
        if name not in HOOK_NAMES:
            logger.warning("[hooks] unknown hook name: " + name)

        if name not in self._hooks:
            self._hooks[name] = []

        rh = RegisteredHook(handler, priority, timeout, once)
        self._hooks[name].append(rh)
        self._hooks[name].sort(key=lambda h: h.priority)

        handler_name = getattr(handler, "__name__", "lambda")
        logger.debug("[hooks] registered " + name + " -> " + handler_name)

    async def trigger(self, name: str, data: Optional[Dict[str, Any]] = None) -> HookContext:
        """Runs all handlers for the given event"""
        ctx = HookContext(name, data or {})
        hooks = self._hooks.get(name, [])

        for rh in hooks:
            if rh.once and rh.fires > 0:
                continue

            try:
                result = rh.handler(ctx)
                if inspect.isawaitable(result):
                    await asyncio.wait_for(result, timeout=rh.timeout)
                # Sync handlers are not awaited (already executed)
                rh.fires += 1
            except asyncio.TimeoutError:
                logger.error("[hooks] " + name + " timeout (" + str(rh.timeout) + "s)")
            except Exception as e:
                logger.error("[hooks] " + name + " error: " + str(e))

            if ctx.cancelled:
                break

        return ctx

    def list(self) -> Dict[str, int]:
        """Returns a map of hook name -> number of handlers"""
        return {name: len(hooks) for name, hooks in self._hooks.items()}

    def clear(self, name: Optional[str] = None) -> None:
        if name:
            self._hooks.pop(name, None)
        else:
            self._hooks.clear()


# Singleton
hooks = HookManager()
