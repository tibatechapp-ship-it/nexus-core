"""Tests for OllamaBackend (v1.40.0)."""
import json
from unittest.mock import patch, MagicMock
from src.core.backend import OllamaBackend


def test_ollama_backend_defaults():
    b = OllamaBackend()
    assert b.model == "sam860/qwen3:1.7b-Q4_K_XL"
    assert b.base_url == "http://127.0.0.1:11434"


def test_ollama_backend_custom():
    b = OllamaBackend(model="llama3:8b", base_url="http://192.168.1.1:11434")
    assert b.model == "llama3:8b"
    assert b.base_url == "http://192.168.1.1:11434"


def test_ollama_backend_trailing_slash_stripped():
    b = OllamaBackend(base_url="http://127.0.0.1:11434/")
    assert b.base_url == "http://127.0.0.1:11434"


@patch("urllib.request.urlopen")
def test_ollama_backend_generate(mock_urlopen):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"response": "OK"}).encode()
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_response

    b = OllamaBackend()
    result = b.generate([{"role": "user", "content": "Say OK"}])
    assert result == "OK"


@patch("urllib.request.urlopen")
def test_ollama_backend_generate_handles_error(mock_urlopen):
    mock_urlopen.side_effect = Exception("connection failed")
    b = OllamaBackend()
    try:
        b.generate([{"role": "user", "content": "Say OK"}])
        assert False, "Expected RuntimeError"
    except RuntimeError as e:
        assert "Ollama request failed" in str(e)


# ── Retry-once behaviour (v1.41.8) ───────────────────────────────────────────

def test_generate_retries_once_on_timeout_then_succeeds(monkeypatch):
    """Transient timeout → one retry → success."""
    import urllib.error
    from unittest.mock import patch
    from src.core.backend import OllamaBackend

    backend = OllamaBackend(model="m", timeout=1.0)
    calls = {"n": 0}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def read(self): return b'{"response": "OK"}'

    def _fake_urlopen(req, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("timed out")
        return _Resp()

    with patch("urllib.request.urlopen", side_effect=_fake_urlopen), \
         patch("time.sleep"):  # skip the 2s backoff
        out = backend.generate([{"role": "user", "content": "hi"}])

    assert out == "OK"
    assert calls["n"] == 2  # retried exactly once


def test_generate_raises_after_two_timeouts(monkeypatch):
    """Persistent timeout → RuntimeError mentioning 'after retry'."""
    import urllib.error
    from unittest.mock import patch
    from src.core.backend import OllamaBackend
    import pytest

    backend = OllamaBackend(model="m", timeout=1.0)

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("nope")), \
         patch("time.sleep"), \
         pytest.raises(RuntimeError, match="after retry"):
        backend.generate([{"role": "user", "content": "hi"}])


def test_generate_does_not_retry_non_retryable_errors(monkeypatch):
    """A non-network error (e.g. bad model) is not retried."""
    from unittest.mock import patch
    from src.core.backend import OllamaBackend
    import pytest

    backend = OllamaBackend(model="m", timeout=1.0)
    calls = {"n": 0}

    def _fake_urlopen(req, timeout):
        calls["n"] += 1
        raise ValueError("bad request")  # not retryable

    with patch("urllib.request.urlopen", side_effect=_fake_urlopen), \
         pytest.raises(RuntimeError, match="Ollama request failed"):
        backend.generate([{"role": "user", "content": "hi"}])

    assert calls["n"] == 1  # no retry
