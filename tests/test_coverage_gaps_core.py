"""Coverage-gap tests — core layer + the ``nexus`` CLI.

Every test here covers a line/branch that the rest of the suite never reaches:
the module bootstrap guards, the defensive ``except`` arms of the CLI status
command, the optional-key-file / HTTP-body fallbacks of the Ollama backend,
the invalid-policy and mixed-payload arms of the resilience helpers, and the
sysfs probes with a missing ``capacity``/``status`` file.
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
from pathlib import Path
from typing import Any, Sequence

import pytest

import src.cli.main as cli
import src.core.ollama_backend as ob
import src.core.sysinfo as sysinfo
from src.core.ollama_backend import OllamaBackend, OllamaError
from src.core.resilience import CommandQueue, ResilientBackend, RetryPolicy, retry_call
from src.core.streaming import iter_stream
from src.core.types import Message
from src.sessions.manager import SessionManager
from src.skills.loader import SkillLoader


def _ns(**kw: Any) -> argparse.Namespace:
    return argparse.Namespace(**kw)


class _FakeBackend:
    keys = ["k1"]
    models = ["m1"]


@pytest.fixture
def isolated_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the CLI's managers at temp dirs and stub the network backend."""
    monkeypatch.setattr(cli, "SessionManager", lambda *a, **k: SessionManager(base_dir=tmp_path / "sessions"))
    monkeypatch.setattr(cli, "SkillLoader", lambda *a, **k: SkillLoader(base_dir=tmp_path / "skills"))
    monkeypatch.setattr(ob, "OllamaBackend", lambda *a, **k: _FakeBackend())


class _BoomRoot:
    """A ROOT stand-in whose agents directory cannot be listed."""

    def __truediv__(self, other: str) -> "_BoomRoot":
        return self

    def glob(self, pattern: str) -> list[Path]:
        raise OSError("boom")


# --------------------------------------------------------------------------- #
# CLI module bootstrap
# --------------------------------------------------------------------------- #
def test_cli_main_reinserts_its_repo_root_on_sys_path() -> None:
    """The guard fires when the interpreter misses the repo root (bare python)."""
    module_file = Path(str(cli.__file__)).resolve()
    root = module_file.parent.parent.parent
    filtered = [p for p in sys.path if Path(p or ".").resolve() not in (root, root / "src")]
    saved = sys.path
    sys.path = filtered
    try:
        namespace: dict[str, Any] = {
            "__name__": "cli_bootstrap_variant",
            "__package__": "src.cli",
            "__file__": str(module_file),
        }
        exec(compile(module_file.read_text(encoding="utf-8"), str(module_file), "exec"), namespace)
        assert str(root) in sys.path
        assert str(root / "src") in sys.path
    finally:
        sys.path = saved


# --------------------------------------------------------------------------- #
# cmd_status / cmd_skills defensive arms
# --------------------------------------------------------------------------- #
def test_cmd_status_with_few_agents_skips_the_overflow_line(
    isolated_cli: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "root"
    agents_dir = root / "src" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "analyst.py").write_text("", encoding="utf-8")
    (agents_dir / "coder.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(cli, "ROOT", root)
    assert cli.cmd_status(_ns()) == 0
    out = capsys.readouterr().out
    assert "👥 Agents: 2" in out
    assert "آخرين" not in out


def test_cmd_status_reports_an_unlistable_agents_dir(
    isolated_cli: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "ROOT", _BoomRoot())
    assert cli.cmd_status(_ns()) == 0
    assert "👥 Agents: ❌ boom" in capsys.readouterr().out


def test_cmd_skills_skips_a_skill_that_fails_to_load(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class GhostLoader:
        def list_skills(self) -> list[str]:
            return ["ghost"]

        def load(self, name: str) -> None:
            return None

    monkeypatch.setattr(cli, "SkillLoader", lambda *a, **k: GhostLoader())
    assert cli.cmd_skills(_ns()) == 0
    out = capsys.readouterr().out
    assert "1 مهارة" in out
    assert "ghost" not in out


# --------------------------------------------------------------------------- #
# Ollama backend fallbacks
# --------------------------------------------------------------------------- #
def test_load_keys_skips_an_unreadable_key_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    active2 = home / ".config" / "zyvo" / "keys" / "active-2"
    active2.mkdir(parents=True)
    (active2 / "boom.key").mkdir()  # a directory named *.key cannot be read
    (active2 / "01.key").write_text("a" * 55, encoding="utf-8")
    monkeypatch.setattr(ob.Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    assert OllamaBackend._load_keys() == ["a" * 55]


class _UnreadableBody:
    def read(self, *args: Any) -> bytes:
        raise OSError("body gone")

    def close(self) -> None:
        """HTTPError's finaliser closes the body it was handed."""


def test_call_http_error_with_unreadable_body(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = OllamaBackend(keys=["k"])

    def raise_http(req: Any, timeout: float) -> Any:
        raise urllib.error.HTTPError("http://x", 500, "server broke", {}, _UnreadableBody())

    monkeypatch.setattr(ob.urllib.request, "urlopen", raise_http)
    with pytest.raises(OllamaError) as exc:
        backend._call("k", "m", [])
    assert "HTTP 500" in str(exc.value)


def test_generate_treats_a_model_error_as_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A "model/404" failure rotates to the next attempt instead of stopping."""
    backend = OllamaBackend(keys=["k1", "k2"], model="m")

    def model_missing(key: str, model: str, messages: Any, max_tokens: int = 2000) -> str:
        raise OllamaError("model m not found (404)")

    monkeypatch.setattr(backend, "_call", model_missing)
    with pytest.raises(OllamaError, match="فشلت كل المحاولات"):
        backend.generate([])


# --------------------------------------------------------------------------- #
# resilience edge cases
# --------------------------------------------------------------------------- #
class _ZeroAttemptPolicy:
    """A duck-typed policy that smuggles in ``max_attempts = 0``.

    ``RetryPolicy`` itself is frozen and rejects that value, so this double is
    the only way to reach :func:`retry_call`'s "the loop never ran" guard — a
    defensive invariant check that keeps the helper from silently returning
    ``None`` with no attempt made.
    """

    max_attempts = 0
    jitter = 0.0

    def delay_for(self, attempt: int) -> float:
        return 0.0


def test_retry_call_with_zero_attempts_fails_loudly() -> None:
    called: list[int] = []
    with pytest.raises(AssertionError):
        retry_call(lambda: called.append(1), _ZeroAttemptPolicy())  # type: ignore[arg-type]
    assert called == []


class _EchoBackend:
    def __init__(self, reply: str = "ok") -> None:
        self.reply = reply
        self.calls: list[str | None] = []

    def generate(self, messages: Sequence[Message], *, model: str | None = None) -> str:
        self.calls.append(model)
        return self.reply


def test_replay_ignores_non_dict_message_entries(tmp_path: Path) -> None:
    queue = CommandQueue(tmp_path / "q.json")
    queue.enqueue(
        {
            "model": "m",
            "messages": [{"role": "user", "content": "keep"}, "not-a-dict"],
        }
    )
    resilient = ResilientBackend(_EchoBackend(), queue=queue, policy=RetryPolicy(max_attempts=1))
    assert resilient.replay() == 1
    assert len(queue) == 0


# --------------------------------------------------------------------------- #
# streaming guard
# --------------------------------------------------------------------------- #
def test_iter_stream_rejects_a_backend_without_generate() -> None:
    with pytest.raises(TypeError, match="not a usable LLM backend"):
        list(iter_stream(object(), [Message("user", "hi")]))


# --------------------------------------------------------------------------- #
# sysfs battery probes
# --------------------------------------------------------------------------- #
def test_battery_returns_none_when_no_supply_reports_capacity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    power = tmp_path / "power_supply"
    (power / "ac").mkdir(parents=True)  # no capacity file at all
    monkeypatch.setattr(sysinfo, "_POWER", power)
    assert sysinfo.battery() is None


def test_battery_reports_unknown_status_without_a_status_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    power = tmp_path / "power_supply"
    battery_dir = power / "battery"
    battery_dir.mkdir(parents=True)
    (battery_dir / "capacity").write_text("42\n", encoding="utf-8")
    monkeypatch.setattr(sysinfo, "_POWER", power)
    assert sysinfo.battery() == {"percent": 42, "status": "unknown", "name": "battery"}


def test_battery_absent_directory_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sysinfo, "_POWER", tmp_path / "missing")
    assert sysinfo.battery() is None
