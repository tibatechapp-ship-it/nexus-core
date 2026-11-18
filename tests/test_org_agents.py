"""اختبارات وقت تشغيل الوكلاء — عقود، صلاحيات أدوات، ذاكرة، محاولات.

القواعد المفروضة: أداة خارج العقد مرفوضة، مفتاح ذاكرة خارج العقد
مرفوض، JSON الفاسد يعاد حتى السقف ثم فشل صريح، وكل تشغيل يترك سجلًا.
"""

from __future__ import annotations

import pytest

from src.org.agents import (
    AgentOutcome,
    AgentRuntime,
    AgentSpec,
    MemoryScope,
    Tool,
    ToolDenied,
    ToolRegistry,
)
from src.org.providers import (
    ProviderConfig,
    ProviderError,
    ProviderPool,
)
from src.org.store import OrgError, OrgStore


@pytest.fixture()
def store() -> OrgStore:
    return OrgStore(":memory:")


@pytest.fixture()
def runtime(store: OrgStore) -> AgentRuntime:
    return AgentRuntime(ProviderPool([ProviderConfig()]), ToolRegistry(),
                        store)


def _spec(**kw: object) -> AgentSpec:
    base: dict[str, object] = {
        "role": "dev:backend", "dept": "development", "mission_id": "m",
        "max_retries": 1,
    }
    base.update(kw)
    return AgentSpec(**base)  # type: ignore[arg-type]


class TestSpecContract:
    def test_role_format_enforced(self) -> None:
        with pytest.raises(ValueError):
            AgentSpec(role="developer", dept="development", mission_id="m")

    def test_unknown_dept_rejected(self) -> None:
        with pytest.raises(ValueError):
            AgentSpec(role="dev:backend", dept="marketing", mission_id="m")

    def test_negative_retries_rejected(self) -> None:
        with pytest.raises(ValueError):
            AgentSpec(role="dev:backend", dept="development", mission_id="m",
                      max_retries=-1)

    def test_system_prompt_declares_role_and_tools(self) -> None:
        spec = _spec(tools=frozenset({"read_repo"}))
        prompt = spec.system_prompt()
        assert "[AGENT:dev:backend]" in prompt
        assert "read_repo" in prompt


class TestToolPermissions:
    def test_unregistered_tool_denied(self, runtime: AgentRuntime) -> None:
        spec = _spec(tools=frozenset({"read_repo"}))
        with pytest.raises(ToolDenied):
            runtime.use_tool(spec, "no_such_tool")

    def test_tool_outside_contract_denied(self, runtime: AgentRuntime) -> None:
        runtime.tools.register(Tool(
            "secret_tool", "أداة حساسة", lambda: {"ok": True}))
        spec = _spec(tools=frozenset({"read_repo"}))
        with pytest.raises(ToolDenied, match="خارج"):
            runtime.use_tool(spec, "secret_tool")

    def test_tool_within_contract_runs(self, runtime: AgentRuntime) -> None:
        runtime.tools.register(Tool("probe", "مسبار", lambda x: {"v": x}))
        spec = _spec(tools=frozenset({"probe"}))
        assert runtime.use_tool(spec, "probe", x=7) == {"v": 7}


class TestMemoryBoundary:
    def test_write_outside_keys_denied(self) -> None:
        scope = MemoryScope("m", "t", frozenset({"plan"}))
        spec = _spec(memory_keys=frozenset({"other"}))
        with pytest.raises(PermissionError):
            scope.remember("plan", {"x": 1}, spec)

    def test_read_outside_keys_returns_none(self) -> None:
        scope = MemoryScope("m", "t", frozenset({"plan"}))
        writer = _spec(memory_keys=frozenset({"plan"}))
        reader = _spec(memory_keys=frozenset({"plan"}))
        scope.remember("plan", {"a": 1}, writer)
        assert scope.recall("plan", reader) == {"a": 1}
        outsider = _spec(role="qa:runner", dept="qa",
                         memory_keys=frozenset({"elsewhere"}))
        assert scope.recall("plan", outsider) is None


class TestAskJson:
    def test_valid_json_parsed(self, runtime: AgentRuntime) -> None:
        out = runtime.ask_json(_spec(), "أجب JSON")
        assert out.success and isinstance(out.data, dict)

    def test_agent_run_logged(self, runtime: AgentRuntime,
                              store: OrgStore) -> None:
        m = store.create_mission(
            __import__("src.org.contracts", fromlist=["Mission"]).Mission(
                title="t", objective="o"))
        spec = _spec(mission_id=m.id)
        runtime.ask_json(spec, "أجب JSON")
        rows = store.agent_runs_for(m.id)
        assert rows and rows[0]["role"] == "dev:backend"
        assert rows[0]["tokens_in"] > 0

    def test_mission_budget_blocks_call_before_provider_dispatch(
            self, store: OrgStore) -> None:
        from src.org.contracts import Mission

        mission = store.create_mission(Mission(title="budget", objective="block"))
        store.configure_mission_output_token_budget(mission.id, 100)
        class MustNotRunPool(ProviderPool):
            def complete_with_fallback(self, messages, **kwargs):  # type: ignore[override]
                raise AssertionError("provider must not be called after budget gate")

        guarded = AgentRuntime(MustNotRunPool(), ToolRegistry(), store)
        spec = _spec(mission_id=mission.id, max_tokens=101)
        with pytest.raises(OrgError, match="مستنفدة"):
            guarded.ask_json(spec, "never dispatch")
        assert store.agent_runs_for(mission.id) == []
        budget = store.mission_output_token_budget(mission.id)
        assert budget is not None
        assert budget["reserved_tokens"] == 0
        assert budget["consumed_tokens"] == 0

    def test_outcome_carries_usage(self, runtime: AgentRuntime) -> None:
        out = runtime.ask_json(_spec(), "أجب JSON")
        assert out.tokens_in > 0 and out.attempts == 1


    def test_unexpected_provider_exception_keeps_budget_reservation_uncertain(
            self, store: OrgStore) -> None:
        from src.org.contracts import Mission

        mission = store.create_mission(
            Mission(title="uncertain call", objective="do not refund"))
        store.configure_mission_output_token_budget(mission.id, 2_000)

        class UncertainPool(ProviderPool):
            def complete_with_fallback(self, messages, **kwargs):  # type: ignore[override]
                raise RuntimeError("transport outcome is unknown")

        runtime = AgentRuntime(UncertainPool(), ToolRegistry(), store)
        with pytest.raises(RuntimeError, match="unknown"):
            runtime.ask_json(_spec(mission_id=mission.id), "call")
        budget = store.mission_output_token_budget(mission.id)
        assert budget is not None
        assert budget["reserved_tokens"] == 2_000
        assert budget["consumed_tokens"] == 0
        reservations = store.mission_output_token_reservations(mission.id)
        assert len(reservations) == 1
        assert reservations[0]["state"] == "reserved"

class TestProviderFailure:
    def test_all_retries_exhausted(self, store: OrgStore) -> None:
        class BoomPool(ProviderPool):
            def complete_with_fallback(self, messages, **kwargs):  # type: ignore[override]
                raise ProviderError("فشل مزوّد")

        runtime = AgentRuntime(BoomPool(), ToolRegistry(), store)
        out = runtime.ask_json(_spec(max_retries=1), "أجب")
        assert out.success is False
        assert out.attempts == 2  # محاولة أولى + إعادة واحدة

    def test_non_dict_json_rejected(self, store: OrgStore) -> None:
        """رد JSON ليس كائنًا يُرفض تحليلًا صريحًا."""
        from src.org.providers import MockProvider, ProviderConfig

        class ListProvider(MockProvider):
            def complete(self, messages, **kwargs):  # type: ignore[override]
                from src.org.providers import ModelResponse, Usage
                return ModelResponse(text="[1, 2]", provider="mock",
                                     model="mock-1", usage=Usage(),
                                     latency_ms=0.1)

        runtime = AgentRuntime(
            ProviderPool([ProviderConfig()]), ToolRegistry(), store)
        runtime.pool.get = lambda name="", model="": ListProvider()  # type: ignore[assignment, return-value]
        out = runtime.ask_json(_spec(max_retries=1), "أجب")
        assert out.success is False
