from nova.registry import REGISTRY

from src.novamind.core.loop_rag_bridge import LoopRAGBridge


class _Rag:
    def __init__(self):
        self.remembered = []

    def recall(self, goal, k=3):
        return []

    def remember(self, text):
        self.remembered.append(text)


class _Agent:
    def __init__(self, result):
        self.result = result

    def build(self, prompt):
        return self.result


def test_loop_bridge_rejects_simulated_output_even_if_custom_criteria_accepts(
    monkeypatch, tmp_path
):
    rag = _Rag()
    monkeypatch.setattr(REGISTRY, "load_agent", lambda name: _Agent({
        "ok": True,
        "simulated": True,
        "provider": "mock",
        "text": "synthetic",
    }))
    bridge = LoopRAGBridge(rag_bridge=rag, state_dir=str(tmp_path))

    result = bridge.run_with_memory(
        goal="build a feature",
        agent_name="coder",
        max_iterations=3,
        success_criteria=lambda _result: True,
        enrich_context=False,
    )

    assert result["status"] == "simulated_result_rejected"
    assert result["iterations"] == 1
    assert result["final_result"]["ok"] is False
    assert rag.remembered == []


def test_loop_bridge_saves_only_real_success(monkeypatch, tmp_path):
    rag = _Rag()
    monkeypatch.setattr(REGISTRY, "load_agent", lambda name: _Agent({
        "ok": True,
        "simulated": False,
        "provider": "test-provider",
        "text": "real contract response",
    }))
    bridge = LoopRAGBridge(rag_bridge=rag, state_dir=str(tmp_path))

    result = bridge.run_with_memory(
        goal="build a feature",
        agent_name="coder",
        max_iterations=1,
        enrich_context=False,
    )

    assert result["status"] == "success"
    assert len(rag.remembered) == 1


def test_loop_bridge_requires_explicit_success_flag_even_with_custom_criteria(
    monkeypatch, tmp_path
):
    rag = _Rag()
    monkeypatch.setattr(REGISTRY, "load_agent", lambda name: _Agent({
        "text": "looks successful",
    }))
    bridge = LoopRAGBridge(rag_bridge=rag, state_dir=str(tmp_path))

    result = bridge.run_with_memory(
        goal="build a feature",
        agent_name="coder",
        max_iterations=3,
        success_criteria=lambda _result: True,
        enrich_context=False,
    )

    assert result["status"] == "missing_explicit_success"
    assert result["iterations"] == 1
    assert result["final_result"]["ok"] is False
    assert rag.remembered == []


def test_loop_bridge_rejects_mock_prefixed_text_without_simulation_flag(
    monkeypatch, tmp_path
):
    rag = _Rag()
    monkeypatch.setattr(REGISTRY, "load_agent", lambda name: _Agent({
        "ok": True,
        "text": "[Mock] synthetic response",
    }))
    bridge = LoopRAGBridge(rag_bridge=rag, state_dir=str(tmp_path))

    result = bridge.run_with_memory(
        goal="build a feature",
        agent_name="coder",
        max_iterations=1,
        enrich_context=False,
    )

    assert result["status"] == "simulated_result_rejected"
    assert result["final_result"]["ok"] is False
    assert rag.remembered == []
