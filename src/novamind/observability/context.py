"""Context propagation — trace_id, span_id, user, task via ContextVar.

أمان async: كل coroutine لها نسختها الخاصة من context.
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Optional


# ═══ ContextVars ═══
_trace_id: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)
_span_id: ContextVar[Optional[str]] = ContextVar("span_id", default=None)
_parent_span_id: ContextVar[Optional[str]] = ContextVar("parent_span_id", default=None)
_attributes: ContextVar[dict] = ContextVar("attributes", default=None)
_task: ContextVar[Optional[str]] = ContextVar("task", default=None)
_user: ContextVar[Optional[str]] = ContextVar("user", default=None)


@dataclass
class TraceContext:
    """Current trace context snapshot."""

    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    task: Optional[str] = None
    user: Optional[str] = None
    attributes: dict = field(default_factory=dict)


# ═══ Getters ═══
def current_trace_id() -> Optional[str]:
    return _trace_id.get()


def current_span_id() -> Optional[str]:
    return _span_id.get()


def current_parent_span_id() -> Optional[str]:
    return _parent_span_id.get()


def current_attributes() -> dict:
    return _attributes.get() or {}


def current_task() -> Optional[str]:
    return _task.get()


def current_user() -> Optional[str]:
    return _user.get()


def snapshot() -> Optional[TraceContext]:
    """Get full current context (None if no trace)."""
    tid = current_trace_id()
    sid = current_span_id()
    if not tid or not sid:
        return None
    return TraceContext(
        trace_id=tid,
        span_id=sid,
        parent_span_id=current_parent_span_id(),
        task=current_task(),
        user=current_user(),
        attributes=dict(current_attributes()),
    )


# ═══ Mutators ═══
def new_trace_id() -> str:
    """Generate a new trace ID (32 hex chars)."""
    return uuid.uuid4().hex


def new_span_id() -> str:
    """Generate a new span ID (16 hex chars)."""
    return uuid.uuid4().hex[:16]


def set_trace_id(trace_id: str) -> None:
    _trace_id.set(trace_id)


def set_span_id(span_id: str) -> None:
    _span_id.set(span_id)


def set_parent_span_id(parent_span_id: Optional[str]) -> None:
    _parent_span_id.set(parent_span_id)


def set_task(task: Optional[str]) -> None:
    _task.set(task)


def set_user(user: Optional[str]) -> None:
    _user.set(user)


def set_attribute(key: str, value: Any) -> None:
    """Add a key to the current context attributes."""
    attrs = current_attributes()
    attrs[key] = value
    _attributes.set(attrs)


def clear() -> None:
    """Reset all context vars (for tests)."""
    _trace_id.set(None)
    _span_id.set(None)
    _parent_span_id.set(None)
    _attributes.set(None)
    _task.set(None)
    _user.set(None)


__all__ = [
    "TraceContext",
    "current_trace_id",
    "current_span_id",
    "current_parent_span_id",
    "current_attributes",
    "current_task",
    "current_user",
    "snapshot",
    "new_trace_id",
    "new_span_id",
    "set_trace_id",
    "set_span_id",
    "set_parent_span_id",
    "set_task",
    "set_user",
    "set_attribute",
    "clear",
]
