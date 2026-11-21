"""يتأكد أن GLM مُعطَّل عند SKIP_GLM=true، وأن groq/gemini أولاً."""
import importlib


def _configure_fake_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVAMIND_HOME", str(tmp_path))
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key-" + "x" * 40)
    monkeypatch.delenv("SKIP_GLM", raising=False)
    for key in (
        "GROQ_API_KEY_1", "ZAI_API_KEY_1", "OPENROUTER_API_KEY_1",
        "MISTRAL_API_KEY_1", "OLLAMA_HOST", "OLLAMA_API_KEY_1",
        "CEREBRAS_API_KEY", "NVIDIA_API_KEY", "SAMBANOVA_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    for prefix, count in (
        ("GROQ_API_KEY_", 20), ("ZAI_API_KEY_", 13),
        ("GEMINI_API_KEY_", 20), ("OPENROUTER_API_KEY_", 11),
        ("MISTRAL_API_KEY_", 9), ("OLLAMA_API_KEY_", 10),
    ):
        for index in range(1, count + 1):
            monkeypatch.delenv(f"{prefix}{index}", raising=False)


def test_skip_glm_removes_glm_providers(monkeypatch, tmp_path):
    _configure_fake_provider(monkeypatch, tmp_path)
    monkeypatch.setenv("SKIP_GLM", "true")
    import novamind.core.llm_router as lr
    importlib.reload(lr)

    router = lr.LLMRouter()
    names = [p.name for p in router.providers]

    assert not any("glm" in n.lower() for n in names), f"GLM still present: {names[:5]}"
    assert names, "no providers loaded"


def test_first_provider_is_not_glm_when_skipped(monkeypatch, tmp_path):
    _configure_fake_provider(monkeypatch, tmp_path)
    monkeypatch.setenv("SKIP_GLM", "true")
    import novamind.core.llm_router as lr
    importlib.reload(lr)

    router = lr.LLMRouter()
    first = router.providers[0].name
    assert not first.startswith("glm-"), f"first provider = {first}"
