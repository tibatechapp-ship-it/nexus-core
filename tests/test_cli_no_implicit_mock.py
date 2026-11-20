from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_cli_scripts_do_not_patch_router_to_mock():
    for name in ("nexus-run", "nexus-loop", "nexus-council-topic", "nexus-council"):
        source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "LLMRouter.generate =" not in source
        assert "mock_gen" not in source
        assert "get_router" in source
        assert "real_providers" in source


def test_explicit_mock_cli_is_visibly_labeled_as_simulation():
    source = (ROOT / "scripts" / "nexus-mock").read_text(encoding="utf-8")
    assert "SIMULATION ONLY" in source
    assert '"simulated": True' in source


def test_shared_mock_router_marks_every_response_as_simulated():
    source = (ROOT / "src" / "llm" / "mock_router.py").read_text(encoding="utf-8")
    assert '"simulated": True' in source


def test_all_mock_cli_tools_are_explicit_and_use_isolated_memory():
    for name, marker in (
        ("nexus-mock", "SIMULATION ONLY"),
        ("nexus-offline", "SIMULATION ONLY"),
        ("nexus-rag-mock", "SIMULATION ONLY"),
    ):
        source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert marker in source
        assert ".cache/nexus-core/simulations/" in source
        assert "simulated" in source
    example = (ROOT / "examples" / "02_agent_run.py").read_text(encoding="utf-8")
    assert "SIMULATION ONLY" in example
    assert "nexus-core-example-simulation" in example
    assert '"simulated": True' in example
