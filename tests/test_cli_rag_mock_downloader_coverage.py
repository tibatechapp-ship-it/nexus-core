"""Focused regression coverage for CLI, local RAG, mock routing and downloader guards."""
from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from src.digital_work import cli as digital_cli
from src.memory import rag_engine
from src.tools import downloader


@pytest.mark.parametrize(
    ("argv", "handler", "result"),
    [
        (["digital-work", "demo", "--output", "proof"], "run_demo", {"mode": "demo"}),
        (["digital-work", "run", "input", "--output", "out", "--run-id", "r1"],
         "execute_run", {"mode": "run"}),
        (["digital-work", "validate", "out"], "validate_run", {"mode": "validate"}),
    ],
)
def test_digital_work_cli_dispatches_each_command(monkeypatch, capsys, argv, handler, result):
    calls = []
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(digital_cli, handler, lambda *a, **kw: calls.append((a, kw)) or result)
    assert digital_cli.main() == 0
    assert calls
    assert '"mode"' in capsys.readouterr().out


def test_digital_work_cli_requires_a_subcommand(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["digital-work"])
    with pytest.raises(SystemExit) as exc:
        digital_cli.main()
    assert exc.value.code == 2


def test_mock_router_installs_deterministic_branches(monkeypatch):
    class LLMRouter:
        pass

    novamind = types.ModuleType("novamind")
    core = types.ModuleType("novamind.core")
    module = types.ModuleType("novamind.core.llm_router")
    module.LLMRouter = LLMRouter
    monkeypatch.setitem(sys.modules, "novamind", novamind)
    monkeypatch.setitem(sys.modules, "novamind.core", core)
    monkeypatch.setitem(sys.modules, "novamind.core.llm_router", module)

    from src.llm.mock_router import setup_mock
    setup_mock()
    router = LLMRouter()
    assert router.generate("راجع الحجتين", "أنت الناقد")["text"] == "بعد المراجعة: متسقتان. مقبول."
    assert router.generate("راجع الحجتين", "أنت المحلل المتشكك")["text"] == "خطر: نقص السياق الأمني."
    assert router.generate("راجع الحجتين", "أنت المحلل المدافع")["text"] == "آمن: يمكن التخفيف."
    assert router.generate("hello", "ordinary")["text"] == "[Mock] hello"
    assert router.generate_for_task("hello")["provider"] == "mock"
    router._load_from_env()
    assert router.providers == []
    assert router._is_cooled_down("provider") is True
    assert router._cooldown_provider("provider") is None


class _FakeStore:
    def __init__(self, *args, **kwargs):
        self.docs = []
        self.closed = False

    def add(self, doc_id, text, embedding, metadata):
        self.docs.append(SimpleNamespace(id=doc_id, text=text, metadata=metadata))

    def search(self, embedding, k=5):
        return self.docs[:k]

    def close(self):
        self.closed = True


def test_rag_engine_add_retrieve_generate_with_and_without_context(monkeypatch, tmp_path):
    monkeypatch.setattr(rag_engine, "SQLiteVecStore", _FakeStore)

    class Embedder:
        dim = 8
        def __call__(self, text):
            return [float(len(text))] * 8

    engine = rag_engine.RAGEngine(str(tmp_path / "vectors.db"), embedder=Embedder())
    assert engine.add_documents([("one", "first"), "invalid", ("two", "second", {})]) == 2
    assert [doc.id for doc in engine.retrieve("query", k=1)] == ["one"]
    generated = engine.generate("what?", k=2)
    assert generated["provider"] == "local-rag"
    assert "[one] first" in generated["text"]
    assert "[two] second" in generated["text"]

    engine.store.docs.clear()
    empty = engine.generate("unknown")
    assert empty["provider"] == "local-rag"
    assert empty["text"] == "[RAG Context]\n\n\n[Query]\nunknown"

    calls = []
    engine.llm = SimpleNamespace(generate_for_task=lambda **kw: calls.append(kw) or {"ok": True})
    assert engine.generate("question", temperature=0.1) == {"ok": True}
    assert calls[0]["task_type"] == "analysis"
    assert calls[0]["temperature"] == 0.1
    engine.close()
    assert engine.store.closed is True


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "http://localhost/a", "http://127.0.0.1/a",
    "http://10.0.0.1/a", "http://[::1]/a", "https:///missing-host",
])
def test_downloader_blocks_unsafe_urls(url):
    assert downloader._is_safe_url(url) is False
    with pytest.raises(ValueError, match="Unsafe URL"):
        downloader.download_file(url)


def test_downloader_requires_output_inside_workspace(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="within the project workspace"):
        downloader.download_file("https://example.com/file", output_dir=str(tmp_path.parent))


def test_downloader_invokes_aria2_and_reports_success(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    observed = {}
    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stderr="")
    monkeypatch.setattr(downloader.subprocess, "run", fake_run)
    result = downloader.download_file("https://example.com/archive.zip", "archive.zip", "downloads")
    assert result == "✅ Download complete: archive.zip"
    assert observed["command"][-1] == "https://example.com/archive.zip"
    assert observed["command"][-3:] == ["-o", "archive.zip", "https://example.com/archive.zip"]
    assert observed["kwargs"]["timeout"] == 3600


def test_downloader_reports_aria2_failure(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        downloader.subprocess, "run",
        lambda *a, **kw: SimpleNamespace(returncode=1, stderr="network failure" * 40),
    )
    with pytest.raises(RuntimeError, match="aria2c failed"):
        downloader.download_file("https://example.com/file")
