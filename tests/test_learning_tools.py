"""Phase 2 Day 1 — hermetic tests for the tool library + the safe_execute gate.

Everything runs offline: ``search_web`` gets an injected fetcher, and the
default DuckDuckGo path is only exercised for its *error* branches (an
unreachable network must yield ``[]``).
"""

from __future__ import annotations

import sys
sys.path.insert(0, '.')

import json
from pathlib import Path

import pytest

from src.learning.tools import (
    MAX_READ_BYTES,
    SEARCH_MAX_RESULTS,
    ToolResult,
    ToolsConfigError,
    default_config,
    get_current_time,
    is_safe_path,
    list_tools,
    load_tools_config,
    query_memory,
    read_file,
    safe_execute,
    save_tools_config,
    search_web,
    tool_explain,
)


def _hits(n: int = 4) -> list[dict[str, str]]:
    return [
        {"title": f"ناتج {i}", "url": f"https://example.com/{i}",
         "snippet": f"مقطع {i}"}
        for i in range(n)
    ]


def _cfg(**overrides):  # noqa: ANN201
    cfg = default_config()
    cfg["tools"].update(overrides)
    return cfg


# ── search_web ────────────────────────────────────────────────────────────
def test_search_web_respects_max_results_and_default():
    assert len(search_web("q", fetcher=lambda _q: _hits(4))) == 3  # default
    assert len(search_web("q", 5, fetcher=lambda _q: _hits(8))) == 5


def test_search_web_clamps_to_the_absolute_ceiling():
    assert len(search_web("q", 999, fetcher=lambda _q: _hits(30))
               ) == SEARCH_MAX_RESULTS


def test_search_web_filters_non_http_urls_and_malformed_hits():
    mixed = [
        {"title": "ok", "url": "https://a.com", "snippet": "s"},
        {"title": "bad-scheme", "url": "javascript:alert(1)", "snippet": ""},
        {"title": "no-url", "snippet": "missing"},
        "not-a-dict",
        {"title": "http-ok", "url": "http://b.com", "snippet": ""},
    ]
    out = search_web("q", 10, fetcher=lambda _q: mixed)
    assert [h["url"] for h in out] == ["https://a.com", "http://b.com"]


def test_search_web_truncates_overlong_fields():
    big = [{"title": "T" * 500, "url": "https://x.com/" + "a" * 900,
            "snippet": "S" * 900}]
    out = search_web("q", 1, fetcher=lambda _q: big)[0]
    assert len(out["title"]) == 200
    assert len(out["url"]) == 500
    assert len(out["snippet"]) == 400


def test_search_web_empty_query_and_fetcher_failure():
    assert search_web("", fetcher=lambda _q: _hits()) == []
    assert search_web("   ", fetcher=lambda _q: _hits()) == []

    def boom(_q):  # noqa: ANN001, ANN202
        raise OSError("network down")

    assert search_web("q", fetcher=boom) == []


def test_search_web_rejects_a_non_list_fetcher():
    assert search_web("q", fetcher=lambda _q: "junk") == []


# ── read_file + is_safe_path ──────────────────────────────────────────────
def test_read_file_returns_content_and_metadata(tmp_path):
    target = tmp_path / "note.md"
    target.write_text("مرحبا", encoding="utf-8")
    out = read_file(str(target), allowed_roots=[str(tmp_path)])
    assert out["content"] == "مرحبا"
    assert out["bytes"] == len("مرحبا".encode("utf-8"))
    assert out["path"].endswith("note.md")


def test_read_file_refuses_traversal_and_symlink_escapes(tmp_path):
    inside = tmp_path / "in"
    inside.mkdir()
    (inside / "ok.txt").write_text("x", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("TOP SECRET", encoding="utf-8")
    link = inside / "link.txt"
    link.symlink_to(outside)

    # traversal out of the allowed root
    with pytest.raises(ValueError):
        read_file(str(inside / ".." / "secret.txt"), allowed_roots=[str(inside)])
    # symlink pointing outside the allowed root
    with pytest.raises(ValueError):
        read_file(str(link), allowed_roots=[str(inside)])
    # missing file
    with pytest.raises(ValueError):
        read_file(str(inside / "nope.txt"), allowed_roots=[str(inside)])


def test_read_file_rejects_oversized_files(tmp_path):
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (MAX_READ_BYTES + 1))
    assert is_safe_path(str(big), allowed_roots=[str(tmp_path)]) is None
    with pytest.raises(ValueError):
        read_file(str(big), allowed_roots=[str(tmp_path)])


def test_is_safe_path_is_none_for_junk_and_directories(tmp_path):
    assert is_safe_path("", allowed_roots=[str(tmp_path)]) is None
    assert is_safe_path(str(tmp_path), allowed_roots=[str(tmp_path)]) is None
    assert is_safe_path(
        str(tmp_path / "ghost.txt"), allowed_roots=[str(tmp_path)]
    ) is None


# ── get_current_time ──────────────────────────────────────────────────────
def test_get_current_time_uses_the_injected_clock():
    out = get_current_time(clock=lambda: 1_000_000.0)
    assert out["unix"] == 1_000_000.0
    assert out["iso"] == "1970-01-12T16:46:40"  # 1e6 s after the epoch


# ── config ────────────────────────────────────────────────────────────────
def test_default_config_loads_and_saves_round_trip(tmp_path):
    path = tmp_path / "tools_config.json"
    saved = save_tools_config(default_config(), path)
    assert saved == path
    assert load_tools_config(path)["tools"].keys() == default_config()["tools"].keys()


def test_missing_config_falls_back_to_default(tmp_path):
    assert load_tools_config(tmp_path / "absent.json") == default_config()


def test_invalid_config_raises_not_silently_falls_back(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ToolsConfigError):
        load_tools_config(bad)

    wrong_shape = tmp_path / "shape.json"
    wrong_shape.write_text(json.dumps({"nope": 1}), encoding="utf-8")
    with pytest.raises(ToolsConfigError):
        load_tools_config(wrong_shape)


def test_list_tools_is_a_read_only_copy():
    cfg = default_config()
    view = list_tools(cfg)
    view["search_web"]["enabled"] = False
    assert cfg["tools"]["search_web"]["enabled"] is True


# ── the Explain feature ───────────────────────────────────────────────────
def test_tool_explain_with_and_without_detail():
    assert tool_explain("search_web", detail="python") == (
        '[استخدمت search_web للبحث عن "python"]'
    )
    assert tool_explain("get_current_time") == "[استخدمت get_current_time]"


# ── safe_execute: the security + transparency gate ────────────────────────
def test_safe_execute_refuses_unknown_and_disabled_tools():
    unknown = safe_execute("not_a_tool")
    assert unknown.ok is False and "غير معروفة" in unknown.error

    disabled_cfg = default_config()
    disabled_cfg["tools"]["execute_code"]["enabled"] = False
    disabled = safe_execute("execute_code", "python", "print(1)",
                            config=disabled_cfg)
    assert disabled.ok is False and "معطّلة" in disabled.error
    assert disabled.tool == "execute_code"


def test_safe_execute_runs_an_enabled_tool_and_explains_it():
    cfg = _cfg(get_current_time={"enabled": True})
    out = safe_execute("get_current_time", config=cfg)
    assert out.ok is True
    assert out.value["unix"] > 0
    assert out.explain == "[استخدمت get_current_time]"


def test_safe_execute_never_raises_on_a_crashing_tool(monkeypatch):
    import src.learning.tools as tools_mod

    def _boom(*_a, **_k):  # noqa: ANN001, ANN202
        raise RuntimeError("internal explosion")

    monkeypatch.setitem(tools_mod._REGISTRY, "get_current_time", (_boom, lambda a, k: ""))
    out = safe_execute("get_current_time")
    assert out.ok is False and "internal explosion" in out.error


def test_safe_execute_passes_config_caps_into_the_tool(monkeypatch):
    """max_results / allowed_roots flow from the config into the call."""
    import src.learning.tools as tools_mod

    seen: dict = {}

    def _spy(*args, **kwargs):  # noqa: ANN001, ANN003
        seen.update(kwargs)
        return []

    monkeypatch.setitem(tools_mod._REGISTRY, "search_web", (_spy, lambda a, k: ""))
    cfg = _cfg(search_web={"enabled": True, "max_results": 7})
    safe_execute("search_web", "q", config=cfg)
    assert seen["max_results"] == 7

    def _spy_read(*args, **kwargs):  # noqa: ANN001, ANN003
        seen.update(kwargs)
        return {}

    monkeypatch.setitem(tools_mod._REGISTRY, "read_file", (_spy_read, lambda a, k: ""))
    cfg2 = _cfg(read_file={"enabled": True, "allowed_roots": ["/tmp"]})
    safe_execute("read_file", "x.txt", config=cfg2)
    assert seen["allowed_roots"] == ["/tmp"]


def test_tool_result_is_a_value_object():
    ok = ToolResult(ok=True, tool="t", value=1, explain="e")
    assert ok and ok.tool == "t"
    assert not ToolResult(ok=False, tool="t", error="x")


# ── Day-2 stubs (present, refused, honest) ────────────────────────────────
def test_query_memory_reads_the_phase1_store(tmp_path):
    from src.learning.interactions import InteractionStore

    store = InteractionStore(str(tmp_path / "ix.db"))
    store.save(agent_id="a", question="كيف أتحقق من كلمة السر",
               answer="استخدم hmac", signal_ok=True)
    rows = query_memory("كلمة السر", store=store)
    assert rows and "hmac" in rows[0]["answer"]


def test_safe_execute_injects_query_memory_limit_from_config():
    seen: dict = {}

    def _spy(keyword, *, store=None, limit=5):  # noqa: ANN001, ANN201
        seen["limit"] = limit
        return []

    import src.learning.tools as tools_mod

    orig = tools_mod._REGISTRY["query_memory"]
    tools_mod._REGISTRY["query_memory"] = (_spy, lambda a, k: "")
    try:
        cfg = _cfg(query_memory={"enabled": True, "limit": 3})
        safe_execute("query_memory", "كلمة", config=cfg)
    finally:
        tools_mod._REGISTRY["query_memory"] = orig
    assert seen["limit"] == 3


def test_execute_code_runs_python_through_the_real_sandbox():
    from src.learning.tools import execute_code

    out = execute_code("python", "print(2+2)")
    assert "4" in str(out.get("stdout", ""))


def test_execute_code_rejects_an_unsupported_language():
    from src.learning.tools import execute_code

    with pytest.raises(ValueError):
        execute_code("cobol", "x")


def test_execute_code_rejects_an_empty_language():
    from src.learning.tools import execute_code

    with pytest.raises(ValueError):
        execute_code("", "x")


def test_day2_tools_are_enabled_by_default():
    cfg = default_config()
    assert cfg["tools"]["query_memory"]["enabled"] is True
    assert cfg["tools"]["execute_code"]["enabled"] is True
    assert cfg["tools"]["execute_code"]["timeout"] == 10


# ── coverage: remaining honest branches ───────────────────────────────────
def test_search_web_defaults_to_the_ddg_fetcher(monkeypatch):
    """No fetcher given → the module's own fetcher is used (patched here)."""
    import src.learning.tools as tools_mod

    calls: list[str] = []

    def _fake(query: str) -> list[dict[str, str]]:  # noqa: ANN001, ANN202
        calls.append(query)
        return _hits(2)

    monkeypatch.setattr(tools_mod, "_ddg_fetch", _fake)
    assert len(search_web("مرحبا")) == 2
    assert calls == ["مرحبا"]


def test_parse_ddg_extracts_hits_and_ignores_junk():
    import src.learning.tools as tools_mod

    html = (
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fa.com">'
        "النتيجة الأولى</a>"
        '<a class="result__snippet">مقطع مختصر</a>'
        '<a class="result__a" href="https://b.com">الثانية</a>'
        '<a class="result__a" href="/relative">بدون عنوان صالح<'  # no </a>
    )
    hits = tools_mod._parse_ddg(html)
    assert [h["url"] for h in hits] == [
        "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fa.com",
        "https://b.com",
    ]
    assert hits[0]["title"] == "النتيجة الأولى"
    assert tools_mod._parse_ddg("<html>no results</html>") == []


def test_ddg_fetch_reads_through_urllib(monkeypatch):
    """Drive _ddg_fetch with a fake urlopen — no network."""
    import src.learning.tools as tools_mod

    class _Resp:
        def __enter__(self):  # noqa: ANN201
            return self

        def __exit__(self, *exc):  # noqa: ANN001, ANN202
            return False

        def read(self, _n: int) -> bytes:  # noqa: ANN001
            return b'<a class="result__a" href="https://c.com">t</a>'

    seen: dict = {}

    def _urlopen(req, timeout=0):  # noqa: ANN001, ANN202
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    hits = tools_mod._ddg_fetch("python")
    assert hits[0]["url"] == "https://c.com"
    assert "python" in seen["url"] and seen["timeout"] == 10


def test_search_web_returns_empty_when_the_default_fetcher_fails(monkeypatch):
    import src.learning.tools as tools_mod

    def _dead(_q):  # noqa: ANN001, ANN202
        raise OSError("no dns")

    monkeypatch.setattr(tools_mod, "_ddg_fetch", _dead)
    assert search_web("q") == []


def test_is_safe_path_skips_an_unresolvable_root(tmp_path):
    good = tmp_path / "ok.txt"
    good.write_text("x", encoding="utf-8")
    # a root that does not exist → resolve(strict=True) raises → skipped,
    # so the file matches no root and is refused.
    assert is_safe_path(str(good), allowed_roots=[str(tmp_path / "ghost_root")]
                        ) is None


def test_read_file_reports_io_errors_as_value_error(tmp_path, monkeypatch):
    target = tmp_path / "a.txt"
    target.write_text("x", encoding="utf-8")

    def _dead(self, *a, **k):  # noqa: ANN001, ANN003, ANN201
        raise OSError("disk went away")

    monkeypatch.setattr(Path, "read_text", _dead)
    with pytest.raises(ValueError, match="تعذّرت"):
        read_file(str(target), allowed_roots=[str(tmp_path)])


def test_query_memory_defaults_to_the_singleton_store(monkeypatch):
    import src.learning.interactions as ix_mod

    class _Fake:
        def similar(self, keyword, k=5, agent_id=None):  # noqa: ANN001, ANN202
            return [{"question": keyword, "k": k, "agent_id": agent_id}]

    monkeypatch.setattr(ix_mod, "get_interaction_store", lambda: _Fake())
    rows = query_memory("سؤال", limit=99)
    assert rows[0]["k"] == 20  # clamped to the 1..20 band


# ── execute_code (Day 2) ──────────────────────────────────────────────────
def test_execute_code_caps_the_output_at_10kb():
    from src.learning.tools import EXEC_OUTPUT_MAX, execute_code

    out = execute_code("python", "print('x' * 20000)")
    assert len(out["stdout"]) == EXEC_OUTPUT_MAX


def test_execute_code_runs_through_an_injected_runner():
    from src.learning.tools import execute_code

    out = execute_code("python", "print(1)",
                       runner=lambda lang, code: {"lang": lang, "code": code})
    assert out == {"lang": "python", "code": "print(1)"}


def test_execute_code_wraps_a_non_dict_sandbox_result(monkeypatch):
    """A non-dict sandbox return is preserved under a ``result`` key."""
    import src.learning.tools as tools_mod

    class _Req:
        def __init__(self, **kw):  # noqa: ANN003
            self.timeout = kw["timeout"]

    class _FakeSandbox:
        LANGS = {"python": "py"}
        ExecReq = _Req
        _run = staticmethod(lambda lang, spec, req, timeout, t0: "RAW")

    monkeypatch.setitem(__import__("sys").modules, "tools.exec_sandbox", _FakeSandbox())
    out = tools_mod.execute_code("python", "x")
    assert out == {"result": "RAW"}


def test_execute_code_executes_real_python_via_the_default_runner():
    from src.learning.tools import execute_code

    out = execute_code("python", "import sys; print(3*7)")
    assert "21" in str(out.get("stdout", ""))


def test_execute_code_honours_a_short_timeout():
    from src.learning.tools import execute_code

    out = execute_code("python", "while True: pass", timeout=1)
    assert out.get("timed_out") is True


def test_safe_execute_injects_execute_code_timeout_from_config():
    import src.learning.tools as tools_mod

    seen: dict = {}

    def _spy(lang, code, timeout=10):  # noqa: ANN001, ANN201
        seen["timeout"] = timeout
        return {}

    orig = tools_mod._REGISTRY["execute_code"]
    tools_mod._REGISTRY["execute_code"] = (_spy, lambda a, k: "")
    try:
        cfg = _cfg(execute_code={"enabled": True, "timeout": 3})
        safe_execute("execute_code", "python", "x", config=cfg)
    finally:
        tools_mod._REGISTRY["execute_code"] = orig
    assert seen["timeout"] == 3


def test_safe_execute_defaults_execute_code_timeout_when_config_omits_it():
    import src.learning.tools as tools_mod

    seen: dict = {}

    def _spy(lang, code, timeout=10):  # noqa: ANN001, ANN201
        seen["timeout"] = timeout
        return {}

    orig = tools_mod._REGISTRY["execute_code"]
    tools_mod._REGISTRY["execute_code"] = (_spy, lambda a, k: "")
    try:
        cfg = _cfg(execute_code={"enabled": True})
        safe_execute("execute_code", "python", "x", config=cfg)
    finally:
        tools_mod._REGISTRY["execute_code"] = orig
    assert seen["timeout"] == 10


def test_safe_execute_keeps_an_explicit_execute_code_timeout():
    """A caller-supplied ``timeout`` must win over the config default."""
    import src.learning.tools as tools_mod

    seen: dict = {}

    def _spy(lang, code, timeout=10):  # noqa: ANN001, ANN201
        seen["timeout"] = timeout
        return {}

    orig = tools_mod._REGISTRY["execute_code"]
    tools_mod._REGISTRY["execute_code"] = (_spy, lambda a, k: "")
    try:
        cfg = _cfg(execute_code={"enabled": True, "timeout": 3})
        safe_execute("execute_code", "python", "x", timeout=7, config=cfg)
    finally:
        tools_mod._REGISTRY["execute_code"] = orig
    assert seen["timeout"] == 7


# ── parse_action (Day 2) ──────────────────────────────────────────────────
def test_parse_action_skips_a_paren_token_that_is_not_a_tool():
    """A regex-matchable token that is not a tool is skipped for a real one."""
    from src.learning.react_agent import parse_action

    assert parse_action("foo(1, 2) ثم query_memory(nexus)") == (
        "query_memory", ["nexus"], {})


def test_parse_action_returns_none_for_empty_and_tool_free_thought():
    from src.learning.react_agent import parse_action

    assert parse_action("") is None
    assert parse_action("   ") is None
    assert parse_action("إن الإجابة هي 4") is None


def test_parse_action_treats_an_unbalanced_call_as_the_rest_of_the_line():
    from src.learning.react_agent import parse_action

    assert parse_action("execute_code(python, print(1)") == (
        "execute_code", ["python", "print(1)"], {})


def test_parse_action_finds_a_bare_tool():
    from src.learning.react_agent import parse_action

    assert parse_action("get_current_time()") == ("get_current_time", [], {})


def test_parse_action_reads_positional_args():
    from src.learning.react_agent import parse_action

    assert parse_action("query_memory(nexus, limit=5)") == (
        "query_memory", ["nexus"], {"limit": 5})


def test_parse_action_keeps_nested_parens_in_the_payload():
    from src.learning.react_agent import parse_action

    tool, args, kwargs = parse_action("execute_code(python, print(2+2))")
    assert tool == "execute_code"
    assert args == ["python", "print(2+2)"]
    assert kwargs == {}


def test_parse_action_reads_keyword_args():
    from src.learning.react_agent import parse_action

    tool, args, kwargs = parse_action(
        "execute_code(python, print(1), timeout=3)")
    assert (tool, args, kwargs) == ("execute_code", ["python", "print(1)"],
                                    {"timeout": 3})


def test_parse_action_coerces_literals():
    from src.learning.react_agent import parse_action

    _, args, kwargs = parse_action(
        'read_file("/a/b.txt", flag=true, missing=none, ratio=2.5, s=\'hi\')')
    assert args == ["/a/b.txt"]
    assert kwargs == {"flag": True, "missing": None, "ratio": 2.5, "s": "hi"}


# ── ReActAgent (Day 2) ────────────────────────────────────────────────────
def _tool_agent(thoughts, results=None):  # noqa: ANN001, ANN201
    """A scripted think() plus a capture list for what safe_execute received."""
    calls: list[tuple[str, tuple, dict]] = []

    def think(question, transcript):  # noqa: ANN001
        return thoughts[len(transcript)] if len(transcript) < len(thoughts) \
            else "إجابة افتراضية"

    return think, calls


def test_react_answer_without_tools_is_final_on_first_step():
    from src.learning.react_agent import ReActAgent

    think, _ = _tool_agent(["الإجابة 4"])
    res = ReActAgent(think, config=_cfg()).run("ما 2+2؟")
    assert res.answer == "الإجابة 4"
    assert res.used_steps == 1
    assert res.stopped_by == "answer"
    assert res.steps[0]["action"] is None


def test_react_runs_a_tool_then_answers():
    from src.learning.react_agent import ReActAgent

    def think(question, transcript):  # noqa: ANN001
        if not transcript:
            return "سألت الوقت get_current_time()"
        return "الآن " + str(transcript[-1]["observation"]["value"])

    res = ReActAgent(think, config=_cfg()).run("كم الساعة؟")
    assert res.used_steps == 2
    assert res.steps[0]["action"] == "get_current_time"
    assert res.steps[0]["observation"]["ok"] is True
    assert res.answer.startswith("الآن ")


def test_react_never_raises_on_a_crashing_tool_and_falls_back():
    from src.learning.react_agent import ReActAgent

    def think(question, transcript):  # noqa: ANN001
        return "جرّب execute_code(python, boom)"

    def _boom(*a, **k):  # noqa: ANN001, ANN003
        raise RuntimeError("kaboom")

    res = ReActAgent(think, config=_cfg(), execute=_boom).run("شغّل")
    assert res.stopped_by == "max_steps"
    assert res.steps[0]["observation"]["ok"] is False
    assert "kaboom" in res.steps[0]["observation"]["error"]
    assert res.answer  # fallback text, never empty, never an exception


def test_react_stops_at_max_steps_when_the_model_never_answers():
    from src.learning.react_agent import ReActAgent

    def think(question, transcript):  # noqa: ANN001
        return "أعد get_current_time()"

    res = ReActAgent(think, config=_cfg(), max_steps=3).run("دائماً")
    assert res.stopped_by == "max_steps"
    assert res.used_steps == 3


def test_react_treats_a_none_thought_as_no_answer():
    from src.learning.react_agent import ReActAgent

    res = ReActAgent(lambda q, t: None, config=_cfg()).run("s")
    assert res.stopped_by == "no_answer"
    assert res.answer  # fallback string, still not empty


def test_react_fallback_uses_successful_observations():
    from src.learning.react_agent import ReActAgent

    def think(question, transcript):  # noqa: ANN001
        return "شغّل execute_code(python, print(42))"

    res = ReActAgent(think, config=_cfg(), max_steps=2).run("n")
    assert "42" in res.answer


def test_react_result_is_a_value_object():
    from src.learning.react_agent import ReActResult

    assert bool(ReActResult(question="q", answer="a")) is True
    assert bool(ReActResult(question="q", answer="")) is False
