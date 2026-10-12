"""
Code Indexer v2 — Stores real code content for semantic search.
"""
import logging
import ast
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("core.rag.code_indexer")

from novamind.core.paths import NOVAMIND_HOME as BASE
DEFAULT_IGNORE = {".git", "__pycache__", "node_modules", ".venv",
                  "venv", "build", "dist", ".pytest_cache",
                  "logs", "memory", "workspace", "platform"}


class CodeIndexer:
    """Builds KG + VS from a directory tree."""

    def __init__(self):
        self.stats = {
            "files_processed": 0,
            "functions": 0,
            "classes": 0,
            "imports": 0,
            "errors": 0,
            "documents_added": 0,
        }
        self._documents: List[Dict] = []

    def _should_skip(self, path: Path) -> bool:
        parts = set(path.parts)
        return bool(parts & DEFAULT_IGNORE)

    def index_python(self, file_path: Path, kg) -> Dict:
        """Index a Python file into KG + collect documents for VS."""
        try:
            code = file_path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(code)
        except SyntaxError as e:
            self.stats["errors"] += 1
            return {"ok": False, "error": f"SyntaxError: {e.msg}"}
        except Exception as e:
            self.stats["errors"] += 1
            return {"ok": False, "error": str(e)[:100]}

        try:
            rel = str(file_path.relative_to(BASE))
        except ValueError:
            rel = str(file_path)

        lines = code.split("\n")

        # File node
        kg.add_node(rel, "file", {
            "lang": "python",
            "lines": len(lines),
            "size": len(code),
            "path": rel,
        })

        # Add file as document
        self._documents.append({
            "id": f"file::{rel}",
            "text": f"{rel} python file {len(lines)} lines {code[:500]}",
            "metadata": {"type": "file", "node_id": rel, "path": rel},
        })

        # Walk AST
        for node in ast.walk(tree):
            # Imports
            if isinstance(node, ast.Import):
                for n in node.names:
                    mod = n.name.split(".")[0]
                    kg.add_edge(rel, f"module::{mod}", "imports")
                    self.stats["imports"] += 1

            elif isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module.split(".")[0]
                kg.add_edge(rel, f"module::{mod}", "imports")
                self.stats["imports"] += 1

            # Functions — store ACTUAL code
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_id = f"fn::{rel}::{node.name}"
                start_line = node.lineno - 1
                end_line = node.end_lineno or node.lineno
                func_code = "\n".join(lines[start_line:end_line])

                # Get docstring
                docstring = ast.get_docstring(node) or ""

                kg.add_node(fn_id, "function", {
                    "name": node.name,
                    "line": node.lineno,
                    "args": len(node.args.args),
                    "is_async": isinstance(node, ast.AsyncFunctionDef),
                    "docstring": docstring[:200],
                    "code_length": len(func_code),
                })
                kg.add_edge(rel, fn_id, "defines")
                self.stats["functions"] += 1

                # Add function AS DOCUMENT with real code
                doc_text = (
                    f"{node.name} {docstring} "
                    f"python function in {rel} "
                    f"{func_code[:800]}"
                )
                self._documents.append({
                    "id": fn_id,
                    "text": doc_text,
                    "metadata": {
                        "type": "function",
                        "node_id": fn_id,
                        "name": node.name,
                        "file": rel,
                        "line": node.lineno,
                    },
                })
                self.stats["documents_added"] += 1

                # Calls within this function
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
                        callee = f"call::{inner.func.id}"
                        kg.add_edge(fn_id, callee, "calls")

            # Classes
            elif isinstance(node, ast.ClassDef):
                cls_id = f"cls::{rel}::{node.name}"
                start_line = node.lineno - 1
                end_line = node.end_lineno or node.lineno
                cls_code = "\n".join(lines[start_line:min(end_line, start_line + 30)])

                docstring = ast.get_docstring(node) or ""

                kg.add_node(cls_id, "class", {
                    "name": node.name,
                    "line": node.lineno,
                    "bases": [b.id for b in node.bases if isinstance(b, ast.Name)],
                    "docstring": docstring[:200],
                })
                kg.add_edge(rel, cls_id, "defines")
                self.stats["classes"] += 1

                # Add class as document
                doc_text = (
                    f"class {node.name} {docstring} "
                    f"in {rel} "
                    f"{cls_code[:600]}"
                )
                self._documents.append({
                    "id": cls_id,
                    "text": doc_text,
                    "metadata": {
                        "type": "class",
                        "node_id": cls_id,
                        "name": node.name,
                        "file": rel,
                        "line": node.lineno,
                    },
                })
                self.stats["documents_added"] += 1

        self.stats["files_processed"] += 1
        return {"ok": True, "file": rel}

    def index_dir(self, directory: Path, kg,
                  max_files: int = 500) -> Dict:
        """Index directory + return collected documents."""
        directory = Path(directory)
        if not directory.exists():
            return {"ok": False, "error": "directory not found"}

        self._documents = []  # reset

        processed = 0
        errors = []

        for py_file in directory.rglob("*.py"):
            if self._should_skip(py_file):
                continue
            if processed >= max_files:
                break

            result = self.index_python(py_file, kg)
            if not result.get("ok"):
                errors.append({"file": str(py_file), "error": result.get("error")})
            processed += 1

        return {
            "ok": True,
            "processed": processed,
            "errors": errors[:10],
            "stats": self.stats,
            "documents": self._documents,
        }

    def reset_stats(self):
        self.stats = {
            "files_processed": 0,
            "functions": 0,
            "classes": 0,
            "imports": 0,
            "errors": 0,
            "documents_added": 0,
        }


code_indexer = CodeIndexer()
__all__ = ["CodeIndexer", "code_indexer"]
