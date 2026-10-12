"""
ReAct Loop — Manual ReAct pattern without LangGraph.

Uses LLMRouter (free: Gemini/Groq) with regex-based tool parsing.

Flow:
  User → LLM → THOUGHT/ACTION → execute → back to LLM → ANSWER
"""
import json
import re
import time
import logging
from typing import Dict, List, Callable, Optional

logger = logging.getLogger("core.react_loop")


REACT_SYSTEM_PROMPT = """You are NovaMind, an expert AI software engineer.

You have access to these tools:

1. analyze_code(task, code)
   - Analyze code for issues
   - task: security_audit | quality_audit | data_audit | devops_audit | full_audit
   - code: the code to analyze

2. read_file(path)
   - Read a project file (relative path)

3. write_file(path, content)
   - Write or create a project file

4. list_files(path)
   - List files/directories in a path

5. git_command(command)
   - Run safe git commands (status, log, diff, branch, show)

## Response Format

To use a tool:
THOUGHT: <your reasoning>
ACTION: <tool_name>
ARGS: {"arg1": "value1", "arg2": "value2"}

To give a final answer:
THOUGHT: <your reasoning>
ANSWER: <final response>

## Rules

- Use ONE tool at a time.
- Always include a THOUGHT line before ACTION or ANSWER.
- ARGS must be valid JSON on ONE line.
- After each tool, you'll see the Observation, then continue.
- For Arabic questions, answer in Arabic.
- Be concise and direct.
"""


class ReactLoop:
    """Manual ReAct loop using LLMRouter."""

    def __init__(self, router, tools: Dict[str, Callable],
                 max_iterations: int = 5):
        self.router = router
        self.tools = tools
        self.max_iterations = max_iterations

    def _parse_response(self, text: str) -> Dict:
        """Parse THOUGHT/ACTION/ARGS or THOUGHT/ANSWER."""
        result = {"thought": "", "action": None, "args": {}, "answer": ""}

        # THOUGHT
        m = re.search(
            r"THOUGHT:\s*(.+?)(?=\n(?:ACTION|ANSWER):|$)",
            text, re.DOTALL | re.IGNORECASE,
        )
        if m:
            result["thought"] = m.group(1).strip()

        # ANSWER (check first — takes priority)
        m = re.search(r"ANSWER:\s*(.+)", text, re.DOTALL | re.IGNORECASE)
        if m:
            result["answer"] = m.group(1).strip()
            return result

        # ACTION
        m = re.search(r"ACTION:\s*(\w+)", text, re.IGNORECASE)
        if m:
            result["action"] = m.group(1).strip()

        # ARGS
        m = re.search(r"ARGS:\s*(\{.*?\})", text, re.DOTALL | re.IGNORECASE)
        if m:
            try:
                result["args"] = json.loads(m.group(1))
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse ARGS: {m.group(1)[:100]}")

        return result

    def _execute_tool(self, name: str, args: Dict) -> str:
        """Execute a tool by name."""
        if name not in self.tools:
            available = ", ".join(self.tools.keys())
            return f"Error: unknown tool '{name}'. Available: {available}"
        try:
            return str(self.tools[name](**args))[:3000]
        except Exception as e:
            return f"Error in '{name}': {type(e).__name__}: {e}"

    def run(self, user_message: str,
            on_event: Optional[Callable[[Dict], None]] = None) -> Dict:
        """
        Run ReAct loop.

        Args:
            user_message: user input
            on_event: optional callback for streaming events:
                - {"type": "thought", "content": ...}
                - {"type": "tool_start", "name": ..., "args": ...}
                - {"type": "tool_end", "name": ..., "observation": ...}
                - {"type": "answer", "content": ...}

        Returns:
            {
              "answer": str,
              "steps": [...],
              "iterations": int,
              "elapsed": float,
            }
        """
        steps = []
        start = time.time()

        def emit(event):
            if on_event:
                try:
                    on_event(event)
                except Exception as e:
                    logger.warning(f"on_event error: {e}")

        prompt = (
            f"User request: {user_message}\n\n"
            "Think step-by-step. Use tools if needed. "
            "End with ANSWER: when done."
        )

        for iteration in range(self.max_iterations):
            # Call LLM
            try:
                result = self.router.generate_for_task(
                    task_type="analysis",
                    prompt=prompt,
                    system=REACT_SYSTEM_PROMPT,
                    temperature=0.1,
                    max_tokens=1500,
                )
            except Exception as e:
                err = f"LLM error: {e}"
                emit({"type": "error", "content": err})
                return {
                    "answer": err, "steps": steps,
                    "iterations": iteration + 1,
                    "elapsed": time.time() - start,
                }

            if not result.get("ok"):
                err = f"LLM failed: {result.get('error', 'unknown')}"
                emit({"type": "error", "content": err})
                return {
                    "answer": err, "steps": steps,
                    "iterations": iteration + 1,
                    "elapsed": time.time() - start,
                }

            text = result.get("text", "")
            parsed = self._parse_response(text)

            # Emit thought
            if parsed["thought"]:
                emit({"type": "thought", "content": parsed["thought"]})

            # Final answer
            if parsed["answer"]:
                steps.append({
                    "iteration": iteration + 1,
                    "thought": parsed["thought"],
                    "answer": parsed["answer"],
                })
                emit({"type": "answer", "content": parsed["answer"]})
                return {
                    "answer": parsed["answer"],
                    "steps": steps,
                    "iterations": iteration + 1,
                    "elapsed": time.time() - start,
                }

            # Tool call
            if parsed["action"]:
                emit({
                    "type": "tool_start",
                    "name": parsed["action"],
                    "args": parsed["args"],
                })

                observation = self._execute_tool(parsed["action"], parsed["args"])

                emit({
                    "type": "tool_end",
                    "name": parsed["action"],
                    "observation": observation[:500],
                })

                steps.append({
                    "iteration": iteration + 1,
                    "thought": parsed["thought"],
                    "action": parsed["action"],
                    "args": parsed["args"],
                    "observation": observation,
                })

                prompt += (
                    f"\n\nAssistant: {text}\n\n"
                    f"Observation: {observation}\n\n"
                    "Continue. If you have the answer, use ANSWER:"
                )
                continue

            # No action, no answer → treat as answer
            steps.append({
                "iteration": iteration + 1,
                "thought": parsed["thought"],
                "raw": text,
            })
            emit({"type": "answer", "content": text})
            return {
                "answer": text.strip(),
                "steps": steps,
                "iterations": iteration + 1,
                "elapsed": time.time() - start,
            }

        # Max iterations
        msg = "Max iterations reached without a final answer."
        emit({"type": "error", "content": msg})
        return {
            "answer": msg,
            "steps": steps,
            "iterations": self.max_iterations,
            "elapsed": time.time() - start,
        }


__all__ = ["ReactLoop", "REACT_SYSTEM_PROMPT"]
