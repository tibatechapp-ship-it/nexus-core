"""Regression tests for downloader URL and workspace confinement."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.tools.downloader import _is_safe_url, download_file


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/archive.zip",
        "https://localhost/archive.zip",
        "https://127.0.0.1/archive.zip",
        "https://10.0.0.2/archive.zip",
        "https://192.168.1.2/archive.zip",
        "https://[::1]/archive.zip",
        "https://0.0.0.0/archive.zip",
        "https://example.com:invalid/archive.zip",
    ],
)
def test_rejects_unsafe_download_urls(url: str) -> None:
    assert _is_safe_url(url) is False


def test_accepts_public_http_and_https_urls() -> None:
    assert _is_safe_url("https://example.com/file.zip") is True
    assert _is_safe_url("http://example.com/file.zip") is True


def test_output_directory_prefix_sibling_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "work"
    sibling = tmp_path / "work-escape"
    workspace.mkdir()
    sibling.mkdir()
    monkeypatch.chdir(workspace)
    with pytest.raises(ValueError, match="within the project workspace"):
        download_file("https://example.com/file.zip", output_dir=str(sibling))


@pytest.mark.parametrize("name", ["../escape.zip", "/tmp/escape.zip", ".", "..", ""])
def test_rejects_output_filename_path_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="plain filename"):
        download_file("https://example.com/file.zip", output_name=name)


def test_download_uses_confined_directory_and_argument_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("src.tools.downloader.subprocess.run", fake_run)
    result = download_file("https://example.com/file.zip", "artifact.zip", ".")
    assert "Download complete" in result
    args = captured["args"]
    assert isinstance(args, list)
    assert args[args.index("-o") + 1] == "artifact.zip"
    assert args[-1] == "https://example.com/file.zip"
