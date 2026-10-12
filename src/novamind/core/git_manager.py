"""
GitManager - Safe Git operations for NovaMind
- Auto-branch per task
- Auto-commit with smart messages
- Rollback support
- Diff generation
"""
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import os

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("git_manager")


class GitError(Exception):
    pass


class GitManager:
    def __init__(self, repo_path: str = os.environ.get("NOVAMIND_HOME", str(Path(__file__).resolve().parent.parent))):
        self.repo = Path(repo_path)
        self._ensure_git_repo()

    def _run(self, args: List[str], check: bool = True) -> Dict:
        """Runs a git command safely."""
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
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "stdout": "", "stderr": "timeout", "returncode": -1}
        except FileNotFoundError:
            return {"ok": False, "stdout": "", "stderr": "git not installed", "returncode": -1}
        except Exception as e:
            return {"ok": False, "stdout": "", "stderr": str(e), "returncode": -1}

    def _ensure_git_repo(self):
        """Initializes git repo if not exists."""
        if not (self.repo / ".git").exists():
            logger.info("initializing git repo at " + str(self.repo))
            self._run(["init"])
            self._run(["config", "user.email", "novamind@local"])
            self._run(["config", "user.name", "NovaMind"])

            # .gitignore
            gitignore = self.repo / ".gitignore"
            if not gitignore.exists():
                gitignore.write_text(
                    "__pycache__/\n*.pyc\n*.pyo\n*.result.json\n*.log\n"
                    "bot_session\n*.session\n.env\n.env.*\n",
                    encoding="utf-8",
                )
                logger.info("created .gitignore")

            self._run(["add", "."])
            self._run(["commit", "-m", "Initial NovaMind commit"])

    def status(self) -> Dict:
        """Returns git status."""
        return self._run(["status", "--short"])

    def is_dirty(self) -> bool:
        """Returns True if there are uncommitted changes."""
        result = self._run(["status", "--short"])
        return bool(result["stdout"].strip())

    def current_branch(self) -> str:
        result = self._run(["branch", "--show-current"])
        return result["stdout"].strip() if result["ok"] else "unknown"

    def list_branches(self) -> List[str]:
        result = self._run(["branch", "--list"])
        if not result["ok"]:
            return []
        return [
            line.strip().lstrip("*").strip()
            for line in result["stdout"].split("\n")
            if line.strip()
        ]

    def create_branch(self, name: str) -> Dict:
        """Creates and switches to a new branch."""
        # Sanitize name
        clean = "".join(c if c.isalnum() or c in "-_" else "-"
                        for c in name)[:50]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        branch = "nova/" + clean + "_" + timestamp

        result = self._run(["checkout", "-b", branch])
        if result["ok"]:
            logger.info("created branch: " + branch)
        return {"branch": branch, **result}

    def add_all(self) -> Dict:
        return self._run(["add", "-A"])

    def commit(self, message: str) -> Dict:
        """Commits current changes."""
        # Add all first
        self.add_all()
        result = self._run(["commit", "-m", message])
        if result["ok"]:
            logger.info("committed: " + message)
        return result

    def commit_smart(self, task_path: str, status: str,
                     attempts: int = 0) -> Dict:
        """Smart commit message based on task outcome."""
        filename = Path(task_path).name
        if status == "passed":
            msg = "Auto: passed " + filename
        elif status == "fixed":
            msg = "Auto: fixed " + filename + " (" + str(attempts) + " attempts)"
        elif status == "failed":
            msg = "Auto: failed " + filename
        else:
            msg = "Auto: " + status + " " + filename
        return self.commit(msg)

    def diff(self, file_path: Optional[str] = None) -> str:
        """Returns diff of changes."""
        args = ["dif"]
        if file_path:
            args.append(file_path)
        result = self._run(args)
        return result["stdout"]

    def diff_vs_branch(self, base_branch: str) -> str:
        """Diff against another branch."""
        result = self._run(["dif", base_branch])
        return result["stdout"]

    def rollback_soft(self) -> Dict:
        """Rollback last commit but keep changes."""
        return self._run(["reset", "--soft", "HEAD~1"])

    def rollback_hard(self) -> Dict:
        """Discard all uncommitted changes."""
        # Reset tracked files
        self._run(["checkout", "--", "."])
        # Clean untracked
        self._run(["clean", "-fd"])
        return {"ok": True, "stdout": "rolled back", "stderr": ""}

    def checkout(self, branch: str) -> Dict:
        """Switch branch."""
        return self._run(["checkout", branch])

    def merge(self, branch: str) -> Dict:
        """Merge branch into current."""
        return self._run(["merge", branch])

    def log(self, limit: int = 10) -> List[Dict]:
        """Recent commits."""
        result = self._run([
            "log", "--oneline", "-" + str(limit),
            "--pretty=format:%h|%s|%cr|%an"
        ])
        if not result["ok"]:
            return []
        commits = []
        for line in result["stdout"].split("\n"):
            parts = line.split("|")
            if len(parts) >= 3:
                commits.append({
                    "hash": parts[0],
                    "message": parts[1],
                    "when": parts[2],
                    "author": parts[3] if len(parts) > 3 else "",
                })
        return commits

    def stats(self) -> Dict:
        return {
            "repo": str(self.repo),
            "current_branch": self.current_branch(),
            "is_dirty": self.is_dirty(),
            "branch_count": len(self.list_branches()),
            "recent_commits": self.log(5),
        }


git_manager = GitManager()
