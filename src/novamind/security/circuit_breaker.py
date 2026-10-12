"""CircuitBreaker v2 — Async-Aware & Time-Window Precise."""
import time
import logging
import asyncio
from enum import Enum
from collections import deque
from typing import Callable, Any, Optional, Union, Coroutine

log = logging.getLogger("CircuitBreaker")


class CircuitState(Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Tripped due to failures
    HALF_OPEN = "half_open" # Testing recovery


class CircuitBreakerError(Exception):
    """Raised when circuit is open and call is rejected."""
    pass


class CircuitBreaker:
    """Advanced Circuit Breaker supporting Sync/Async and Sliding Time Windows.

    Features:
    - Supports both synchronous functions and coroutines.
    - Uses a sliding time window for failure detection (more accurate than count-only).
    - Automatic state transitions (CLOSED -> OPEN -> HALF_OPEN -> CLOSED/OPEN).
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
        failure_window_seconds: Optional[float] = None,
    ):
        """
        Args:
            name: Identifier for metrics/logging.
            failure_threshold: Number of consecutive failures within window to trip breaker.
            recovery_timeout: Seconds to wait in OPEN state before trying HALF_OPEN.
            half_open_max_calls: Max trial calls allowed in HALF_OPEN state.
            failure_window_seconds: Lookback period for counting failures. Defaults to recovery_timeout.
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.failure_window = failure_window_seconds or recovery_timeout

        self.state = CircuitState.CLOSED
        self._failure_timestamps: deque = deque()
        self.last_failure_time: float = 0.0
        self.half_open_attempt_count: int = 0
        
        # Metrics
        self.total_calls = 0
        self.total_failures = 0
        self.total_successes = 0

    def _prune_old_failures(self):
        """Remove failures outside the sliding time window."""
        now = time.time()
        cutoff = now - self.failure_window
        while self._failure_timestamps and self._failure_timestamps[0] < cutoff:
            self._failure_timestamps.popleft()

    def _should_trip(self) -> bool:
        """Check if current failure count exceeds threshold within window."""
        self._prune_old_failures()
        return len(self._failure_timestamps) >= self.failure_threshold

    def allow_request(self) -> bool:
        """Determines if a request should be processed based on current state."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                log.info(f"[{self.name}] State change: OPEN -> HALF_OPEN")
                self.state = CircuitState.HALF_OPEN
                self.half_open_attempt_count = 0
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            if self.half_open_attempt_count < self.half_open_max_calls:
                self.half_open_attempt_count += 1
                return True
            return False

        return False

    def record_success(self):
        """Records a successful execution."""
        self.total_calls += 1
        self.total_successes += 1
        
        if self.state == CircuitState.HALF_OPEN:
            log.info(f"[{self.name}] Recovery confirmed. State: HALF_OPEN -> CLOSED")
            self.state = CircuitState.CLOSED
            self._failure_timestamps.clear()
        
        elif self.state == CircuitState.CLOSED:
            # Success resets the immediate failure streak conceptually, 
            # but we keep history in window for statistical accuracy unless configured otherwise.
            # For strict "consecutive" logic, we might clear, but for rate-based, we keep.
            # Here we assume rate-based (failures in last N seconds).
            pass

    def record_failure(self):
        """Records a failed execution."""
        self.total_calls += 1
        self.total_failures += 1
        now = time.time()
        self._failure_timestamps.append(now)
        self.last_failure_time = now

        if self.state == CircuitState.HALF_OPEN:
            log.warning(f"[{self.name}] Trial failed. State: HALF_OPEN -> OPEN")
            self.state = CircuitState.OPEN
            return

        if self.state == CircuitState.CLOSED and self._should_trip():
            log.error(
                f"[{self.name}] Threshold breached ({len(self._failure_timestamps)} fails in {self.failure_window}s). "
                f"State: CLOSED -> OPEN"
            )
            self.state = CircuitState.OPEN

    async def acall(self, func: Callable[..., Coroutine], *args, **kwargs) -> Any:
        """Executes an async function with circuit breaking protection."""
        if not self.allow_request():
            raise CircuitBreakerError(f"Circuit '{self.name}' is OPEN. Request rejected.")

        try:
            result = await func(*args, **kwargs)
            
            # Handle dict results that indicate logical failure (e.g., {"ok": False})
            if isinstance(result, dict) and not result.get("ok", True):
                self.record_failure()
            else:
                self.record_success()
                
            return result
            
        except Exception as e:
            self.record_failure()
            raise

    def call(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        """Executes a sync function with circuit breaking protection."""
        if not self.allow_request():
            raise CircuitBreakerError(f"Circuit '{self.name}' is OPEN. Request rejected.")

        try:
            result = func(*args, **kwargs)
            
            if isinstance(result, dict) and not result.get("ok", True):
                self.record_failure()
            else:
                self.record_success()
                
            return result
            
        except Exception as e:
            self.record_failure()
            raise

    def get_stats(self) -> dict:
        """Returns current health statistics."""
        self._prune_old_failures() # Ensure fresh data
        return {
            "name": self.name,
            "state": self.state.value,
            "active_failures_in_window": len(self._failure_timestamps),
            "total_calls": self.total_calls,
            "total_failures": self.total_failures,
            "success_rate": round(self.total_successes / self.total_calls, 4) if self.total_calls > 0 else 0.0,
            "last_failure_time": self.last_failure_time,
        }

    def reset(self):
        """Manually resets the breaker to CLOSED state."""
        self.state = CircuitState.CLOSED
        self._failure_timestamps.clear()
        self.half_open_attempt_count = 0
        log.info(f"[{self.name}] Manually RESET to CLOSED.")


# ═══ Global Registry ═══
_registry: dict[str, CircuitBreaker] = {}


def get_breaker(name: str, **config_kwargs) -> CircuitBreaker:
    """Retrieves or creates a named CircuitBreaker instance."""
    if name not in _registry:
        _registry[name] = CircuitBreaker(name=name, **config_kwargs)
    return _registry[name]


def get_all_breakers_stats() -> list[dict]:
    """Aggregates stats from all registered breakers."""
    return [cb.get_stats() for cb in _registry.values()]
