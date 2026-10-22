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
