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
    return AgentRuntime(ProviderPool([ProviderConfig(name="mock", model="mock-1")]), ToolRegistry(),
                        store, allow_simulated=True)


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

    @pytest.mark.parametrize("value", [True, 0, -1, "100", 2**63])
    def test_invalid_max_tokens_rejected(self, value: object) -> None:
        with pytest.raises(ValueError, match="max_tokens"):
            _spec(max_tokens=value)  # type: ignore[arg-type]


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


    def test_configured_mission_budget_is_enforced_and_settled(
            self, runtime: AgentRuntime, store: OrgStore) -> None:
        from src.org.contracts import Mission

        mission = store.create_mission(Mission(title="bounded", objective="agent call"))
        store.configure_mission_token_budget(mission.id, 2500)
        outcome = runtime.ask_json(
            _spec(mission_id=mission.id, max_tokens=2000), "أجب JSON")
        assert outcome.success
        budget = store.mission_token_budget_get(mission.id)
        assert budget is not None
        assert budget["reserved_output_tokens"] == 0
        assert budget["consumed_output_tokens"] == outcome.tokens_out

    def test_insufficient_mission_budget_blocks_provider_dispatch(
            self, store: OrgStore) -> None:
        from src.org.contracts import Mission

        class MustNotRunPool(ProviderPool):
            def complete_with_fallback(self, messages, **kwargs):  # type: ignore[override]
                raise AssertionError("provider must not be called")

        mission = store.create_mission(Mission(title="blocked", objective="no dispatch"))
        store.configure_mission_token_budget(mission.id, 100)
        runtime = AgentRuntime(MustNotRunPool(), ToolRegistry(), store)
        with pytest.raises(OrgError, match="ميزانية توكنات الخرج"):
            runtime.ask_json(
                _spec(mission_id=mission.id, max_tokens=200), "أجب JSON")
        budget = store.mission_token_budget_get(mission.id)
        assert budget["reserved_output_tokens"] == 0
        assert budget["consumed_output_tokens"] == 0

    def test_provider_fallback_failures_are_charged_conservatively(
            self, store: OrgStore, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.org.contracts import Mission

        mission = store.create_mission(Mission(
            title="fallback budget", objective="charge failed dispatches"))
        store.configure_mission_token_budget(mission.id, 5000)
        pool = ProviderPool([
            ProviderConfig(name="first", model="first-model"),
            ProviderConfig(name="mock", model="mock-1"),
        ])

        class UncertainProvider:
            def complete(self, messages, **kwargs):
                raise ProviderError("timeout after possible provider dispatch")

        original_get = pool.get

        def get_provider(name: str = "", model: str = ""):
            if name == "first":
                return UncertainProvider()
            return original_get(name, model)

        monkeypatch.setattr(pool, "get", get_provider)
        runtime = AgentRuntime(pool, ToolRegistry(), store, allow_simulated=True)
        outcome = runtime.ask_json(
            _spec(mission_id=mission.id, max_tokens=1000, max_retries=0),
            "أجب JSON",
        )

        assert outcome.success
        budget = store.mission_token_budget_get(mission.id)
        assert budget is not None
        assert budget["reserved_output_tokens"] == 0
        assert budget["consumed_output_tokens"] >= 1000 + outcome.tokens_out

    def test_outcome_carries_usage(self, runtime: AgentRuntime) -> None:
        out = runtime.ask_json(_spec(), "أجب JSON")
        assert out.tokens_in > 0 and out.attempts == 1


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
            ProviderPool([ProviderConfig(name="mock", model="mock-1")]), ToolRegistry(), store, allow_simulated=True)
        runtime.pool.get = lambda name="", model="": ListProvider()  # type: ignore[assignment, return-value]
        out = runtime.ask_json(_spec(max_retries=1), "أجب")
        assert out.success is False
