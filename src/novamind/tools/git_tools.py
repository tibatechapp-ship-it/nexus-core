"""Git tools for the agent"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.base import Tool, ToolResult, registry
from core.git_manager import git_manager


class GitStatusTool(Tool):
    name = "git_status"
    description = "Get git status."
    danger_level = "safe"

    def parameters_schema(self):
        return {"type": "object", "properties": {}}

    def run(self):
        try:
            return ToolResult(ok=True, data=git_manager.stats())
        except Exception as e:
            return ToolResult(ok=False, error=str(e)[:200])


class GitCommitTool(Tool):
    name = "git_commit"
    description = "Commit all changes with a message."
    danger_level = "warn"

    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        }

    def run(self, message):
        try:
            result = git_manager.commit(message)
            return ToolResult(ok=result.get("ok", False), data={
                "message": message,
                "output": result.get("stdout", "")[:200],
            }, error=result.get("stderr", ""))
        except Exception as e:
            return ToolResult(ok=False, error=str(e)[:200])


class GitLogTool(Tool):
    name = "git_log"
    description = "Show recent git commits."
    danger_level = "safe"

    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 10}},
        }

    def run(self, limit=10):
        try:
            return ToolResult(ok=True, data={"commits": git_manager.log(limit)})
        except Exception as e:
            return ToolResult(ok=False, error=str(e)[:200])


class GitDiffTool(Tool):
    name = "git_dif"
    description = "Get diff of uncommitted changes."
    danger_level = "safe"

    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
        }

    def run(self, file_path=None):
        try:
            diff = git_manager.diff(file_path)
            return ToolResult(ok=True, data={"dif": diff[:10000]})
        except Exception as e:
            return ToolResult(ok=False, error=str(e)[:200])


registry.register(GitStatusTool())
registry.register(GitCommitTool())
registry.register(GitLogTool())
registry.register(GitDiffTool())
