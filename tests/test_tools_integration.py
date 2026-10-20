"""End-to-end smoke tests for the agent tool library (``src/learning/tools``).

One test per registered tool, driven through the single public entry point
:func:`safe_execute` — exactly the way a ReAct agent calls them.  The point is
to prove each tool is *wired* (registry entry + config gate + callable), not to
re-test each tool's internals (they have their own suites).

Rules kept here:
* No network.  ``download_file`` is exercised on its SSRF guard (localhost) and
  ``search_web`` on the empty-query short-circuit; the live-network paths are
  covered by their own suites.
* No real sandbox dependency: ``execute_code`` injects a fake runner so the test
  is hermetic and fast.
* File tools use ``tmp_path`` and pass an explicit ``allowed_roots``.

"""

from __future__ import annotations

from pathlib import Path

from src.learning.tools import _REGISTRY, list_tools, safe_execute


def _config(tool: str, **settings: object) -> dict:
    """Build a minimal one-tool config with the tool enabled."""
    return {"tools": {tool: {"enabled": True, **settings}}}


# ── the registry contract ────────────────────────────────────────────────
def test_registry_holds_all_seven_tools() -> None:
    """The vocabulary the ReAct parser relies on must be exactly these 7."""
    assert set(_REGISTRY) == {
        "search_web",
        "read_file",
        "get_current_time",
        "query_memory",
        "execute_code",
        "consensus",
        "download_file",
    }


def test_default_config_enables_every_registered_tool() -> None:
    """Every registry entry must be reachable through the shipped config."""
    enabled = {name for name, s in list_tools().items() if s.get("enabled")}
    assert set(_REGISTRY) <= enabled


# ── per-tool smoke tests ─────────────────────────────────────────────────
def test_search_web_empty_query_is_a_noop() -> None:
    """An empty query short-circuits before any network call."""
    result = safe_execute("search_web", query="", config=_config("search_web"))
    assert result.ok
    assert result.value == []


def test_read_file_reads_a_real_file(tmp_path: Path) -> None:
    """read_file is confined to allowed_roots and returns the text."""
    target = tmp_path / "note.txt"
    target.write_text("hello tools", encoding="utf-8")
    result = safe_execute(
        "read_file",
        path=str(target),
        config=_config("read_file", allowed_roots=[str(tmp_path)]),
    )
    assert result.ok
    assert result.value["content"] == "hello tools"


def test_read_file_refuses_a_path_outside_the_root(tmp_path: Path) -> None:
    """A file outside the allowed root is a clean ok=False, never a raise."""
    outside = tmp_path / "outside.txt"
    outside.write_text("nope", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    result = safe_execute(
        "read_file",
        path=str(outside),
        config=_config("read_file", allowed_roots=[str(root)]),
    )
    assert not result.ok
    assert result.error


def test_get_current_time_returns_iso_and_unix() -> None:
    """The clock tool is wired and returns both representations."""
    result = safe_execute("get_current_time", config=_config("get_current_time"))
    assert result.ok
    assert isinstance(result.value["unix"], float)
    assert "T" in result.value["iso"]


def test_query_memory_returns_a_list() -> None:
    """query_memory is wired; an empty store is still a successful call."""
    result = safe_execute(
        "query_memory", keyword="anything",
        config=_config("query_memory", limit=3),
    )
    assert result.ok
    assert isinstance(result.value, list)


def test_execute_code_runs_through_the_configured_runner() -> None:
    """execute_code dispatches to the sandbox runner (faked here → hermetic)."""
    calls: list[tuple[str, str]] = []

    def fake_runner(language: str, code: str) -> dict:
        calls.append((language, code))
        return {"stdout": "4", "exit_code": 0}

    result = safe_execute(
        "execute_code", language="python", code="print(2+2)",
        runner=fake_runner, config=_config("execute_code"),
    )
    assert result.ok
    assert result.value["stdout"] == "4"
    assert calls == [("python", "print(2+2)")]


def test_consensus_wires_injected_agents() -> None:
    """consensus is reachable through safe_execute with injected LLM fakes."""
    result = safe_execute(
        "consensus",
        question="is the sky blue",
        agents=["a", "b", "c"],
        ask_fn=lambda agent, q: f"{agent}: yes",
        synthesize_fn=lambda q, answers: "combined",
        config=_config("consensus"),
    )
    assert result.ok
    assert result.value["agents_used"] == ["a", "b", "c"]
    assert "agreement" in result.value


def test_download_file_blocks_ssrf_before_any_download() -> None:
    """The downloader's SSRF guard fires on a loopback URL (no network)."""
    result = safe_execute(
        "download_file", url="http://127.0.0.1/x",
        config=_config("download_file"),
    )
    assert not result.ok
    assert "SSRF" in (result.error or "")
