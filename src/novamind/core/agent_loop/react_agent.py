"""
ReAct Agent Loop — Reason → Act → Observe → Repeat
Modern agentic AI pattern (2026).
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Callable
import os

logger = logging.getLogger("agent_loop.react")

BASE = Path(os.environ.get("NOVAMIND_HOME", str(Path(__file__).resolve().parent.parent)))


class Thought:
    def __init__(self, phase: str, content: str, tool: str = "",
                 args: Dict = None, result: Dict = None):
        self.phase = phase  # reason | act | observe
        self.content = content
        self.tool = tool
        self.args = args or {}
        self.result = result or {}
        self.at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict:
        return {
            "phase": self.phase,
            "content": self.content,
            "tool": self.tool,
            "args": self.args,
            "result": self.result,
            "at": self.at,
        }


class ReActAgent:
    """
    ReAct agent loop with tool calling.

    Flow:
      1. Reason — decide what to do
      2. Act   — call a tool
      3. Observe — inspect result
      4. Repeat until goal achieved or max steps
    """

    def __init__(self, repo_id: str = "R-000", max_steps: int = 10):
        self.repo_id = repo_id
        self.max_steps = max_steps
        self.trace: List[Thought] = []

    # ═══════════════════════════════════════════════════════
    #  Tool registry
    # ═══════════════════════════════════════════════════════
    def _tools(self) -> Dict[str, Callable]:
        return {
            "read_file":       self._tool_read_file,
            "write_file":      self._tool_write_file,
            "list_pr":         self._tool_list_pr,
            "review_pr":       self._tool_review_pr,
            "detect_errors":   self._tool_detect_errors,
            "suggest_fix":     self._tool_suggest_fix,
            "comment_pr":      self._tool_comment_pr,
            "report":          self._tool_report,
            "finish":          self._tool_finish,
        }

    # ═══════════════════════════════════════════════════════
    #  Individual tools
    # ═══════════════════════════════════════════════════════
    def _tool_read_file(self, path: str) -> Dict:
        try:
            p = Path(path)
            if not p.is_absolute():
                p = BASE / path
            return {"ok": True, "content": p.read_text(encoding="utf-8")[:10000]}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def _tool_write_file(self, path: str, content: str) -> Dict:
        try:
            p = Path(path)
            if not p.is_absolute():
                p = BASE / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {"ok": True, "written": str(p), "size": len(content)}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def _tool_list_pr(self, repo: str = "", state: str = "open") -> Dict:
        try:
            from integration.github_client import get_github
            gh = get_github()
            r = gh._request("GET", f"/repos/{repo}/pulls?state={state}&per_page=10")
            if not r.get("ok"):
                return {"ok": False, "error": r.get("error", "")}
            prs = [{"number": p["number"], "title": p["title"][:80],
                    "user": p["user"]["login"]} for p in r["data"]]
            return {"ok": True, "prs": prs, "count": len(prs)}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def _tool_review_pr(self, repo: str, pr_number: int, dry_run: bool = True) -> Dict:
        try:
            from integration.pr_reviewer import pr_reviewer
            r = pr_reviewer.review_pr(repo, pr_number, dry_run=dry_run,
                                       generate_tests=False)
            return r
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def _tool_detect_errors(self, code: str, filename: str = "") -> Dict:
        try:
            from novamind.core.analysis.error_detector import error_detector
            return error_detector.detect(code, filename)
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def _tool_suggest_fix(self, code: str, issues: List[Dict],
                          lang: str = "python") -> Dict:
        try:
            from novamind.core.analysis.fix_suggester import fix_suggester
            return fix_suggester.suggest(code, issues, lang, use_llm=False)
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def _tool_comment_pr(self, repo: str, pr_number: int, body: str) -> Dict:
        try:
            from integration.github_client import get_github
            gh = get_github()
            r = gh.post_pr_comment(repo, pr_number, body)
            return r
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def _tool_report(self, data: Dict, name: str = "report") -> Dict:
        try:
            from novamind.core.repo_manager import repo_manager
            r = repo_manager.get(self.repo_id)
            if r:
                f = r.save_report(name, data)
                return {"ok": True, "saved": str(f)}
            return {"ok": False, "error": "repo not found"}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def _tool_finish(self, summary: str = "") -> Dict:
        return {"ok": True, "finished": True, "summary": summary[:500]}

    # ═══════════════════════════════════════════════════════
    #  LLM-based reasoning
    # ═══════════════════════════════════════════════════════
    def _reason(self, goal: str, history: List[Thought]) -> Dict:
        """Ask LLM to decide next action."""
        try:
            from novamind.core.providers.orchestrator import orchestrator
        except ImportError:
            return {"tool": "finish", "args": {"summary": "orchestrator unavailable"}}

        # Build prompt
        available_tools = ", ".join(self._tools().keys())
        history_text = "\n".join(
            f"[{t.phase.upper()}] {t.content[:120]}"
            + (f" (tool={t.tool})" if t.tool else "")
            for t in history[-5:]
        ) or "(بداية)"

        prompt = f"""أنت وكيل ذكي اسمه NovaMind. هدفك:

{goal}

التاريخ:
{history_text}

الأدوات المتاحة: {available_tools}

اختر الأداة التالية. أجب بصيغة JSON فقط:

{{"tool": "اسم_الأداة", "args": {{...}}, "reason": "لماذا"}}

قواعد:
- إذا انتهى الهدف، استخدم finish
- args يجب أن تكون صحيحة للأداة
- لا تخترع أدوات غير موجودة
"""

        result = orchestrator.call(prompt, task="smart", max_tokens=500)

        if not result.get("ok"):
            return {"tool": "finish", "args": {"summary": "LLM failed: " + result.get("error", "")[:80]}}

        text = result.get("text", "").strip()

        # Strip markdown
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        # Parse JSON
        try:
            # Find JSON object
            import re
            m = re.search(r'\{[\s\S]*\}', text)
            if m:
                decision = json.loads(m.group(0))
                return {
                    "tool": decision.get("tool", "finish"),
                    "args": decision.get("args", {}),
                    "reason": decision.get("reason", ""),
                }
        except Exception as e:
            logger.warning(f"LLM response not JSON: {text[:200]}")

        return {"tool": "finish", "args": {"summary": "invalid LLM response"}}

    # ═══════════════════════════════════════════════════════
    #  Main loop
    # ═══════════════════════════════════════════════════════
    def run(self, goal: str) -> Dict:
        logger.info(f"[{self.repo_id}] ReAct goal: {goal[:100]}")
        self.trace = []

        for step in range(1, self.max_steps + 1):
            # ── REASON ──
            decision = self._reason(goal, self.trace)
            tool_name = decision.get("tool", "finish")
            args = decision.get("args", {})
            reason = decision.get("reason", "")

            thought = Thought("reason", reason or f"اخترت {tool_name}", tool=tool_name, args=args)
            self.trace.append(thought)

            # ── ACT ──
            tools = self._tools()
            if tool_name not in tools:
                obs = {"ok": False, "error": f"unknown tool: {tool_name}"}
            else:
                try:
                    obs = tools[tool_name](**args)
                except Exception as e:
                    obs = {"ok": False, "error": str(e)[:200]}

            # ── OBSERVE ──
            obs_thought = Thought("observe", f"{tool_name} → ok={obs.get('ok', False)}",
                                   tool=tool_name, result=obs)
            self.trace.append(obs_thought)

            # ── FINISH? ──
            if tool_name == "finish" or obs.get("finished"):
                return {
                    "ok": True,
                    "steps": step,
                    "goal": goal,
                    "summary": obs.get("summary", ""),
                    "trace": [t.to_dict() for t in self.trace],
                }

        return {
            "ok": False,
            "reason": f"max steps ({self.max_steps}) reached",
            "goal": goal,
            "trace": [t.to_dict() for t in self.trace],
        }


react_agent = ReActAgent
