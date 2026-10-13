"""
Robust parser tests: accept multiple tool-call formats.

Discovery: Agent integration test (Phase 2.3, 2026-10-13) — real LLMs emit
``<tool-call name="x"></tool-call>`` (no args) and child-text JSON, but the
parser required ``args='...'``, so tools silently never ran.

Fix (Postel's law): src/tools/executor._TOOL_CALL_RE + parse_tool_calls now
accept all four forms below. See AGENTS.md "Finding: MCP Parser".
"""

from __future__ import annotations

from src.tools.executor import parse_tool_calls


class TestParserRobustness:
    def test_no_args_pair_form(self):
        """LLM format #1: no args, pair tags."""
        calls = parse_tool_calls('<tool-call name="git_status"></tool-call>')
        assert len(calls) == 1
        assert calls[0].name == "git_status"
        assert calls[0].arguments == {}

    def test_no_args_self_closing(self):
        """Self-closing without args."""
        calls = parse_tool_calls('<tool-call name="git_branches"/>')
        assert len(calls) == 1
        assert calls[0].name == "git_branches"
        assert calls[0].arguments == {}

    def test_with_args_attr_single_quotes(self):
        """Canonical form: args as quoted JSON attribute."""
        calls = parse_tool_calls('<tool-call name="git_log" args=\'{"limit": 3}\'></tool-call>')
        assert len(calls) == 1
        assert calls[0].name == "git_log"
        assert calls[0].arguments == {"limit": 3}

    def test_with_args_attr_double_quotes(self):
        """Canonical form with a double-quoted attribute (simple JSON)."""
        calls = parse_tool_calls('<tool-call name="read" args="{}"/>')
        assert len(calls) == 1
        assert calls[0].name == "read"
        assert calls[0].arguments == {}

    def test_escaped_quotes_in_attr_degrades_safely(self):
        """An attr with escaped inner quotes is malformed for the lazy matcher —
        it must degrade to {} (documented), never crash. Models should use
        single-quoted attrs."""
        calls = parse_tool_calls('<tool-call name="grep" args="{\\"p\\": \\"x\\"}"/>')
        assert calls[0].arguments == {}

    def test_with_child_json(self):
        """LLM format #3: JSON as child text."""
        calls = parse_tool_calls('<tool-call name="git_log">\n  {"limit": 2}\n</tool-call>')
        assert len(calls) == 1
        assert calls[0].name == "git_log"
        assert calls[0].arguments == {"limit": 2}

    def test_child_text_non_json_is_empty(self):
        """Child text that is not JSON degrades to empty args, never crashes."""
        calls = parse_tool_calls("<tool-call name=\"x\">plain words</tool-call>")
        assert len(calls) == 1
        assert calls[0].name == "x"
        assert calls[0].arguments == {}

    def test_multiple_mixed_formats(self):
        """Every tolerated format in one response, in order."""
        text = (
            '<tool-call name="git_status"></tool-call>\n'
            '<tool-call name="git_log" args=\'{"limit": 3}\'/>\n'
            '<tool-call name="git_show">{"ref": "HEAD"}</tool-call>'
        )
        calls = parse_tool_calls(text)
        assert [c.name for c in calls] == ["git_status", "git_log", "git_show"]
        assert calls[1].arguments == {"limit": 3}
        assert calls[2].arguments == {"ref": "HEAD"}

    def test_malformed_args_cannot_crash(self):
        """Non-JSON args degrade to {} (documented contract)."""
        calls = parse_tool_calls('<tool-call name="read" args=\'not json\'/>')
        assert calls[0].arguments == {}

    def test_no_tool_calls(self):
        """Plain model output -> no calls."""
        assert parse_tool_calls("Just a normal answer.") == []
        assert parse_tool_calls("") == []