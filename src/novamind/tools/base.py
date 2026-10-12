"""
Tool base classes and registry
"""
import logging
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger("tools.base")


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str = ""
    elapsed: float = 0.0
    tool_name: str = ""

    def to_dict(self):
        return {
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "elapsed": round(self.elapsed, 3),
            "tool": self.tool_name,
        }


class Tool:
    name = "base_tool"
    description = ""
    danger_level = "safe"

    def __init__(self):
        self.stats = {"calls": 0, "failures": 0, "total_time": 0.0}

    def run(self, **kwargs):
        raise NotImplementedError

    def _run_wrapped(self, **kwargs):
        start = time.time()
        try:
            result = self.run(**kwargs)
            result.tool_name = self.name
            result.elapsed = time.time() - start
            self.stats["calls"] += 1
            self.stats["total_time"] += result.elapsed
            if not result.ok:
                self.stats["failures"] += 1
            return result
        except Exception as e:
            elapsed = time.time() - start
            self.stats["calls"] += 1
            self.stats["failures"] += 1
            self.stats["total_time"] += elapsed
            logger.error("tool " + self.name + " error: " + str(e))
            return ToolResult(ok=False, error=str(e)[:200], elapsed=elapsed,
                              tool_name=self.name)

    def schema(self):
        return {
            "name": self.name,
            "description": self.description,
            "danger_level": self.danger_level,
            "parameters": self.parameters_schema(),
        }

    def parameters_schema(self):
        return {"type": "object", "properties": {}}


class ToolRegistry:
    def __init__(self):
        self.tools = {}

    def register(self, tool):
        self.tools[tool.name] = tool
        logger.info("registered tool: " + tool.name)

    def get(self, name):
        return self.tools.get(name)

    def list_tools(self):
        return sorted(self.tools.keys())

    def schemas(self):
        return [t.schema() for t in self.tools.values()]

    def run(self, name, **kwargs):
        tool = self.get(name)
        if not tool:
            return ToolResult(ok=False, error="unknown tool: " + name,
                              tool_name=name)
        return tool._run_wrapped(**kwargs)

    def stats(self):
        return {
            "total_tools": len(self.tools),
            "tools": {name: dict(t.stats) for name, t in self.tools.items()},
        }


registry = ToolRegistry()
