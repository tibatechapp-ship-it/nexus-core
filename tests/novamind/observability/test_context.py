"""Tests for observability.context module."""
from __future__ import annotations

import pytest

from novamind.observability import context as ctx


class TestContextBasics:

    def setup_method(self) -> None:
        ctx.clear()

    def test_initial_state_is_none(self) -> None:
        assert ctx.current_trace_id() is None
        assert ctx.current_span_id() is None
        assert ctx.current_task() is None
        assert ctx.current_user() is None

    def test_new_trace_id_is_32_hex(self) -> None:
        tid = ctx.new_trace_id()
        assert len(tid) == 32
        assert all(c in "0123456789abcdef" for c in tid)

    def test_new_span_id_is_16_hex(self) -> None:
        sid = ctx.new_span_id()
        assert len(sid) == 16
        assert all(c in "0123456789abcdef" for c in sid)

    def test_set_and_get_trace_id(self) -> None:
        tid = "a" * 32
        ctx.set_trace_id(tid)
        assert ctx.current_trace_id() == tid

    def test_set_and_get_span_id(self) -> None:
        sid = "b" * 16
        ctx.set_span_id(sid)
        assert ctx.current_span_id() == sid

    def test_set_task_and_user(self) -> None:
        ctx.set_task("fix bug")
        ctx.set_user("alice")
        assert ctx.current_task() == "fix bug"
        assert ctx.current_user() == "alice"

    def test_snapshot_returns_none_without_trace(self) -> None:
        ctx.clear()
        assert ctx.snapshot() is None

    def test_snapshot_with_trace(self) -> None:
        ctx.set_trace_id("a" * 32)
        ctx.set_span_id("b" * 16)
        ctx.set_task("test")
        snap = ctx.snapshot()
        assert snap is not None
        assert snap.trace_id == "a" * 32
        assert snap.span_id == "b" * 16
        assert snap.task == "test"

    def test_set_attribute(self) -> None:
        ctx.set_attribute("key1", "value1")
        attrs = ctx.current_attributes()
        assert attrs["key1"] == "value1"

    def test_clear_resets_everything(self) -> None:
        ctx.set_trace_id("x")
        ctx.set_task("y")
        ctx.clear()
        assert ctx.current_trace_id() is None
        assert ctx.current_task() is None
