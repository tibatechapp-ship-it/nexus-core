"""Phase 2 Day 2 — a ReAct (Reason + Act) agent loop.

The agent answers a question by interleaving reasoning with tool calls:

    Thought → Action → Observation → Thought → … → Answer

* **Thought/Answer** come from an injectable ``think`` callable (an LLM).  It
  receives the question and the running transcript and returns the next
  *thought*, or the final *answer* once it has enough evidence.
* **Action** is one :func:`~src.learning.tools.safe_execute` call.  The loop
  parses ``tool_name(arg1, arg2, key=value)`` out of the thought; a thought
  with no action is treated as the final answer.
* **Observation** is the :class:`~src.learning.tools.ToolResult` (``ok``,
  ``value``/``error``, ``explain``) fed back into the next thought.

Design notes:

* The loop **never raises**: a malformed action or a failing tool becomes an
  ``observation`` the model can see and route around, exactly like
  ``safe_execute`` never raises for the caller.
* Everything is injectable (``think``, ``config``, ``tools``) so the whole
  loop is hermetically testable at 100% coverage with a fake LLM and fake
  tools — no network, no sandbox.
* ``max_steps`` bounds the loop so a runaway model can never spin forever.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from src.learning.tools import ToolResult, _REGISTRY, load_tools_config, safe_execute

__all__ = [
    "MAX_STEPS_DEFAULT",
    "ReActAgent",
    "ReActResult",
    "parse_action",
]

MAX_STEPS_DEFAULT = 10

# The known tool vocabulary — used to pick the *outermost* tool call.
_TOOL_NAMES = frozenset(_REGISTRY)

# ``tool_name(`` — we only need the call site; args are cut by bracket matching.
_TOOL_CALL_RE = re.compile(r"(?P<tool>[a-zA-Z_][a-zA-Z0-9_]*)\s*\(")


@dataclass(frozen=True)
class ReActResult:
    """Outcome of one :meth:`ReActAgent.run` — never an exception."""

    question: str
    answer: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    used_steps: int = 0
    stopped_by: str = "answer"   # "answer" | "max_steps" | "no_answer"

    def __bool__(self) -> bool:  # pragma: no cover - trivial convenience
        return bool(self.answer)


def _coerce(value: str) -> Any:
    """Turn an action-argument literal into a Python value, leniently."""
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    low = text.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("none", "null"):
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _find_call(thought: str) -> tuple[str, str] | None:
    """Find the first known-tool call; return ``(tool_name, raw_args)``.

    Bracket-matching (not a regex on ``[^()]*``) so a payload that contains
    commas and parens — ``execute_code(python, print(2+2))`` — is kept whole.
    """
    for match in _TOOL_CALL_RE.finditer(thought):
        name = match.group("tool")
        if name not in _TOOL_NAMES:
            continue
        open_at = thought.index("(", match.start())
        depth = 0
        for pos in range(open_at, len(thought)):
            ch = thought[pos]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return name, thought[open_at + 1:pos].strip()
        # Unbalanced call — treat the rest of the line as the argument text.
        return name, thought[open_at + 1:].strip()
    return None


def _emit_arg(chunk: str, positional: list[Any], keyword: dict[str, Any]) -> None:
    """Route one comma-split chunk into positional args or keyword args."""
    piece = chunk.strip()
    if not piece:
        return
    if "=" in piece and not piece.split("=", 1)[0].strip().isnumeric():
        key, _, val = piece.partition("=")
        keyword[key.strip()] = _coerce(val)
    else:
        positional.append(_coerce(piece))


def _split_args(raw: str) -> tuple[list[Any], dict[str, Any]]:
    """Split ``raw`` on top-level commas only (ignores commas in quotes/parens)."""
    positional: list[Any] = []
    keyword: dict[str, Any] = {}
    depth = 0
    quote: str | None = None
    buf: list[str] = []
    for ch in raw:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            _emit_arg("".join(buf), positional, keyword)
            buf = []
        else:
            buf.append(ch)
    _emit_arg("".join(buf), positional, keyword)
    return positional, keyword


def parse_action(thought: str) -> tuple[str, list[Any], dict[str, Any]] | None:
    """Extract ``tool(args, kwargs)`` from ``thought``; ``None`` = no action.

    Returns ``(tool_name, positional_args, keyword_args)``.  The *first* known
    tool call in the thought wins (models wrap payloads in nested calls).
    """
    if not thought:
        return None
    found = _find_call(thought)
    if found is None:
        return None
    tool, raw = found
    positional, keyword = _split_args(raw)
    return tool, positional, keyword


class ReActAgent:
    """Drive one question through the Thought→Action→Observation loop."""

    def __init__(
        self,
        think: Callable[[str, list[dict[str, Any]]], str],
        *,
        config: dict[str, Any] | None = None,
        max_steps: int = MAX_STEPS_DEFAULT,
        execute: Callable[..., ToolResult] | None = None,
    ) -> None:
        """``think(question, transcript) -> next thought or final answer``."""
        self._think = think
        self._config = config
        self._max_steps = max(1, int(max_steps))
        self._execute = execute or safe_execute

    def run(self, question: str) -> ReActResult:
        """Run the loop until the model answers or ``max_steps`` is hit."""
        transcript: list[dict[str, Any]] = []
        steps: list[dict[str, Any]] = []
        answer = ""
        stopped_by = "no_answer"

        for step_no in range(1, self._max_steps + 1):
            thought = self._think(question, transcript)
            if thought is None:  # defensive: a model returning None
                stopped_by = "no_answer"
                break
            thought = str(thought)
            parsed = parse_action(thought)

            if parsed is None:
                # No action marker → this thought is the final answer.
                answer, stopped_by = thought, "answer"
                steps.append({"thought": thought, "action": None,
                              "observation": None})
                break

            tool, args, kwargs = parsed
            cfg = self._config if self._config is not None else load_tools_config()
            try:
                result: ToolResult = self._execute(
                    tool, *args, config=cfg, **kwargs)
            except Exception as exc:  # noqa: BLE001 - the loop must never raise
                result = ToolResult(ok=False, tool=tool, error=str(exc),
                                    explain="")
            observation: dict[str, Any] = {
                "ok": result.ok,
                "tool": result.tool,
                "value": result.value,
                "error": result.error,
                "explain": result.explain,
            }
            steps.append({"thought": thought, "action": tool,
                          "observation": observation})
            transcript.append({"thought": thought, "observation": observation})
        else:
            # Loop exhausted without an answer-only thought.
            stopped_by = "max_steps"

        if not answer and stopped_by != "answer":
            answer = self._fallback_answer(steps, question)

        return ReActResult(
            question=question, answer=answer, steps=steps,
            used_steps=len(steps), stopped_by=stopped_by,
        )

    def _fallback_answer(self, steps: list[dict[str, Any]],
                         question: str) -> str:
        """Build a best-effort answer when the model never says "Answer"."""
        obs = [s["observation"] for s in steps if s.get("observation", {}).get("ok")]
        if not obs:
            return f"لم أجد إجابة موثوقة للسؤال: {question}"
        parts = []
        for o in obs:
            value = o.get("value")
            if isinstance(value, dict) and "stdout" in value:
                parts.append(str(value["stdout"]).strip())
            else:
                parts.append(str(value))
        return "\n".join(p for p in parts if p)
