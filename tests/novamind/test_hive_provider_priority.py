"""يتأكد أن GLM مُعطَّل عند SKIP_GLM=true، وأن groq/gemini أولاً."""
import importlib


def test_skip_glm_removes_glm_providers(monkeypatch):
    monkeypatch.setenv("SKIP_GLM", "true")
    import novamind.core.llm_router as lr
    importlib.reload(lr)

    router = lr.LLMRouter()
    names = [p.name for p in router.providers]

    assert not any(n.startswith("glm-") for n in names), f"GLM still present: {names[:5]}"
    assert names, "no providers loaded"


def test_first_provider_is_not_glm_when_skipped(monkeypatch):
    monkeypatch.setenv("SKIP_GLM", "true")
    import novamind.core.llm_router as lr
    importlib.reload(lr)

    router = lr.LLMRouter()
    first = router.providers[0].name
    assert not first.startswith("glm-"), f"first provider = {first}"
