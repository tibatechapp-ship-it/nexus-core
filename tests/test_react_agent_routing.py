"""End-to-end routing proof for the ReAct agent (``src/learning/react_agent``).

The ReAct loop is *automatic*: the model is never handed a tool menu, it simply
writes a thought that contains a ``tool_name(...)`` call and the loop's parser
(:func:`parse_action`) picks it up, executes it through ``safe_execute``, and
feeds the :class:`ToolResult` back as the next observation.

This test proves that whole chain with a fake LLM and the *real* tool library:
the fake thought names ``download_file`` with a loopback URL, so the real
``safe_execute`` must run and return the SSRF refusal.  Seeing that refusal in
the agent's transcript is the proof that the tool was actually called — no
network, no guessing about the model's output format.
"""

from __future__ import annotations

from typing import Any

from src.learning.react_agent import ReActAgent
from src.learning.tools import safe_execute


class _FakeLLM:
    """Returns a scripted list of thoughts, ignoring the transcript."""

    def __init__(self, thoughts: list[str]) -> None:
        self._thoughts = thoughts
        self._i = 0
        self.seen_transcripts: list[list[dict[str, Any]]] = []

    def generate(self, question: str, transcript: list[dict[str, Any]]) -> str:
        self.seen_transcripts.append([dict(s) for s in transcript])
        thought = self._thoughts[min(self._i, len(self._thoughts) - 1)]
        self._i += 1
        return thought


def test_react_agent_routes_a_thought_to_the_real_tool() -> None:
    """A thought naming download_file must reach safe_execute and come back.

    The loop's action syntax is ``tool_name(args)`` inside the thought text
    (see ``react_agent.parse_action``) — not a ``Thought:/Action:`` protocol —
    so the fake model emits exactly that call form.
    """
    llm = _FakeLLM([
        'Thought: the user wants a download\ndownload_file("http://127.0.0.1/x")',
        "Answer: the download was blocked",
    ])
    agent = ReActAgent(llm.generate, execute=safe_execute)

    result = agent.run("Download something")

    # 1) The loop ran the tool exactly once and captured its observation.
    actions = [s["action"] for s in result.steps if s.get("action")]
    assert actions == ["download_file"]

    observation = next(
        s["observation"] for s in result.steps if s.get("action") == "download_file"
    )
    # 2) The observation is the real tool's result: SSRF refusal, ok=False.
    assert observation["ok"] is False
    assert observation["tool"] == "download_file"
    assert "SSRF" in (observation["error"] or "")

    # 3) The tool result was fed back to the model before it answered.
    assert result.stopped_by == "answer"
    assert result.answer == "Answer: the download was blocked"
    second_call_transcript = llm.seen_transcripts[1]
    assert second_call_transcript, "the model must receive the observation"
    assert second_call_transcript[0]["observation"]["tool"] == "download_file"
