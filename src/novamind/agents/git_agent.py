"""
GitAgent - Executes Git operations via natural language
"""
import logging
import sys
import subprocess
import re
from pathlib import Path
from typing import Dict, List
import os

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("agents.git")


class GitAgent:
    def __init__(self, repo_path: str = os.environ.get("NOVAMIND_HOME", str(Path(__file__).resolve().parent.parent))):
        self.repo = Path(repo_path)
        self.name = "git_agent"

    def _run(self, args: List[str]) -> Dict:
        """Runs a git command."""
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=str(self.repo),
                capture_output=True,
                text=True,
                timeout=30,
            )
            return {
                "ok": result.returncode == 0,
                "stdout": (result.stdout or "")[-2000:],
                "stderr": (result.stderr or "")[-1000:],
                "returncode": result.returncode,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def status(self) -> Dict:
        return self._run(["status", "--short"])

    def add(self, path: str = ".") -> Dict:
        return self._run(["add", path])

    def commit(self, message: str) -> Dict:
        self.add(".")
        return self._run(["commit", "-m", message])

    def push(self, remote: str = "origin", branch: str = "main") -> Dict:
        return self._run(["push", remote, branch])

    def pull(self, remote: str = "origin", branch: str = "main") -> Dict:
        return self._run(["pull", remote, branch])

    def branch(self, name: str) -> Dict:
        return self._run(["checkout", "-b", name])

    def checkout(self, name: str) -> Dict:
        return self._run(["checkout", name])

    def log(self, limit: int = 10) -> Dict:
        return self._run(["log", "--oneline", "-" + str(limit)])

    def diff(self, file_path: str = None) -> Dict:
        args = ["dif"]
        if file_path:
            args.append(file_path)
        return self._run(args)

    def parse_command(self, text: str) -> Dict:
        """
        Parses natural language git command.
        Examples:
          "commit with message 'fix bug'"
          "push to origin main"
          "create branch feature-x"
        """
        text_lower = text.lower()

        # Commit
        if "commit" in text_lower:
            match = re.search(r"['\"]([^'\"]+)['\"]", text)
            msg = match.group(1) if match else "Auto commit by NovaMind"
            return {"action": "commit", "message": msg}

        # Push
        if "push" in text_lower:
            return {"action": "push", "remote": "origin", "branch": "main"}

        # Pull
        if "pull" in text_lower:
            return {"action": "pull", "remote": "origin", "branch": "main"}

        # Branch
        if "branch" in text_lower:
            match = re.search(r"branch\s+(\S+)", text_lower)
            name = match.group(1) if match else "new-branch"
            return {"action": "branch", "name": name}

        # Status
        if "status" in text_lower:
            return {"action": "status"}

        # Log
        if "log" in text_lower:
            return {"action": "log"}

        return {"action": "unknown", "text": text}

    def execute(self, text: str) -> Dict:
        """Executes a natural language git command."""
        cmd = self.parse_command(text)
        action = cmd.get("action")

        if action == "commit":
            return self.commit(cmd.get("message", "Auto commit"))
        elif action == "push":
            return self.push(cmd.get("remote", "origin"), cmd.get("branch", "main"))
        elif action == "pull":
            return self.pull(cmd.get("remote", "origin"), cmd.get("branch", "main"))
        elif action == "branch":
            return self.branch(cmd.get("name", "new-branch"))
        elif action == "status":
            return self.status()
        elif action == "log":
            return self.log()

        return {"ok": False, "error": "unknown git command"}


git_agent = GitAgent()
