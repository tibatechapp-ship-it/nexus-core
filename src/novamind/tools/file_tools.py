"""File system tools"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.base import Tool, ToolResult, registry
from core.vfs import vfs, VfsError


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read the contents of a file."
    danger_level = "safe"

    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_bytes": {"type": "integer", "default": 50000},
            },
            "required": ["path"],
        }

    def run(self, path, max_bytes=50000):
        try:
            content = vfs.read(path)
            truncated = False
            if len(content) > max_bytes:
                content = content[:max_bytes]
                truncated = True
            return ToolResult(ok=True, data={
                "path": path, "content": content,
                "size": len(content), "truncated": truncated,
            })
        except VfsError as e:
            return ToolResult(ok=False, error=str(e))
        except Exception as e:
            return ToolResult(ok=False, error=str(e)[:200])


class WriteFileTool(Tool):
    name = "write_file"
    description = "Write content to a file."
    danger_level = "warn"

    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        }

    def run(self, path, content):
        try:
            vfs.write(path, content)
            return ToolResult(ok=True, data={
                "path": path, "bytes": len(content.encode("utf-8")),
            })
        except VfsError as e:
            return ToolResult(ok=False, error=str(e))
        except Exception as e:
            return ToolResult(ok=False, error=str(e)[:200])


class ListDirTool(Tool):
    name = "list_dir"
    description = "List files and directories in a path."
    danger_level = "safe"

    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "default": "."}},
        }

    def run(self, path="."):
        try:
            items = vfs.list_dir(path)
            return ToolResult(ok=True, data={
                "path": path, "items": items, "count": len(items),
            })
        except Exception as e:
            return ToolResult(ok=False, error=str(e)[:200])


class SearchFilesTool(Tool):
    name = "search_files"
    description = "Search for a pattern in files under a directory."
    danger_level = "safe"

    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "default": "."},
                "max_results": {"type": "integer", "default": 30},
            },
            "required": ["pattern"],
        }

    def run(self, pattern, path=".", max_results=30):
        try:
            root = Path(path)
            if not root.is_absolute():
                root = Path(os.environ.get("NOVAMIND_HOME", str(Path(__file__).resolve().parent.parent))) / path
            if not root.exists():
                return ToolResult(ok=False, error="path not found: " + path)

            results = []
            for f in root.rglob("*"):
                if not f.is_file():
                    continue
                if any(p.startswith(".") for p in f.parts):
                    continue
                if f.stat().st_size > 500_000:
                    continue
                try:
                    for i, line in enumerate(
                            f.read_text(encoding="utf-8", errors="ignore").split("\n"), 1):
                        if pattern in line:
                            results.append({"file": str(f), "line": i,
                                            "text": line.strip()[:200]})
                            if len(results) >= max_results:
                                break
                    if len(results) >= max_results:
                        break
                except Exception:
                    continue

            return ToolResult(ok=True, data={
                "pattern": pattern, "results": results,
                "count": len(results),
            })
        except Exception as e:
            return ToolResult(ok=False, error=str(e)[:200])


class EditFileTool(Tool):
    name = "edit_file"
    description = "Replace a unique string in a file."
    danger_level = "warn"

    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old": {"type": "string"},
                "new": {"type": "string"},
            },
            "required": ["path", "old", "new"],
        }

    def run(self, path, old, new):
        try:
            content = vfs.read(path)
            count = content.count(old)
            if count == 0:
                return ToolResult(ok=False, error="old string not found")
            if count > 1:
                return ToolResult(ok=False,
                                  error="appears " + str(count) + " times")
            new_content = content.replace(old, new, 1)
            vfs.write(path, new_content)
            return ToolResult(ok=True, data={"path": path, "changed": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e)[:200])


registry.register(ReadFileTool())
registry.register(WriteFileTool())
registry.register(ListDirTool())
registry.register(SearchFilesTool())
registry.register(EditFileTool())
