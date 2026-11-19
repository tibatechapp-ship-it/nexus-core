"""Bounded, evidence-grounded source retrieval for the coding engine.

The retrieval pass is deterministic and read-only: defect paths and direct
Python imports are prioritized, then lexical relevance ranks source files
across supported languages. No repository code is executed.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

MAX_FILES = 8
MAX_FILE_BYTES = 8 * 1024
MAX_TOTAL_CHARS = 32 * 1024
MAX_INDEX_FILES = 3000
MAX_INDEX_FILE_BYTES = 64 * 1024
SOURCE_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".go", ".rs", ".java", ".kt", ".kts", ".php", ".rb", ".cs",
    ".swift", ".dart", ".vue", ".sql",
}
SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules", "dist",
    "build", ".next", ".pytest_cache", ".mypy_cache", "vendor", "target",
}
SENSITIVE_PARTS = {
    ".env", ".env.local", ".env.production", "secrets", "secret",
    "credentials", "credential", "private", "certs",
}
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")


def _tokens(value: str) -> list[str]:
    """Normalize identifiers and prose into deterministic lexical terms."""
    normalized: list[str] = []
    for token in TOKEN_RE.findall(value):
        camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", token)
        normalized.extend(
            part.lower() for part in re.split(r"[_\s]+", camel_split) if len(part) > 2
        )
    return normalized


def _safe_relative(root: Path, value: str) -> Path | None:
    """Return an in-repository source file, rejecting traversal and secrets."""
    if not value or Path(value).is_absolute():
        return None
    candidate = (root / value).resolve()
    try:
        relative = candidate.relative_to(root.resolve())
    except ValueError:
        return None
    if any(part.lower() in SENSITIVE_PARTS for part in relative.parts):
        return None
    if candidate.suffix.lower() not in SOURCE_SUFFIXES:
        return None
    if any(part in SKIP_DIRS or part.startswith(".") for part in relative.parts):
        return None
    return candidate if candidate.is_file() else None


def _module_paths(modules: list[dict[str, Any]]) -> dict[str, str]:
    """Map dotted Python module names to repository-relative paths."""
    return {
        str(item["name"]): str(item["path"])
        for item in modules
        if isinstance(item, dict) and item.get("name") and item.get("path")
    }


def _lexical_rank(
    root: Path,
    query: str,
    excluded: set[str],
) -> list[str]:
    """Rank source files with a bounded BM25-style lexical retrieval pass."""
    terms = set(_tokens(query))
    if not terms:
        return []
    documents: list[tuple[str, Counter[str], int]] = []
    document_frequency: Counter[str] = Counter()
    for path in sorted(root.rglob("*")):
        if len(documents) >= MAX_INDEX_FILES:
            break
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if relative in excluded or _safe_relative(root, relative) is None:
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if len(raw) > MAX_INDEX_FILE_BYTES:
            raw = raw[:MAX_INDEX_FILE_BYTES]
        try:
            source = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            continue
        tokens = _tokens(relative + " " + source)
        if not tokens:
            continue
        counts = Counter(tokens)
        documents.append((relative, counts, len(tokens)))
        document_frequency.update(set(counts).intersection(terms))
    if not documents:
        return []
    average_length = sum(item[2] for item in documents) / len(documents)
    total_docs = len(documents)
    scored: list[tuple[float, str]] = []
    for relative, counts, length in documents:
        score = 0.0
        for term in terms:
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            inverse = math.log(
                1.0 + (total_docs - document_frequency[term] + 0.5)
                / (document_frequency[term] + 0.5)
            )
            denominator = frequency + 1.2 * (
                0.25 + 0.75 * length / max(average_length, 1.0)
            )
            score += inverse * frequency * 2.2 / denominator
        if score > 0:
            scored.append((score, relative))
    return [
        relative for _, relative in sorted(scored, key=lambda item: (-item[0], item[1]))
    ]


def build_code_context(
    root: Path | str,
    repo_context: dict[str, Any],
    defects: list[dict[str, Any]],
    *,
    goal: str = "",
    max_files: int = MAX_FILES,
    max_file_bytes: int = MAX_FILE_BYTES,
    max_total_chars: int = MAX_TOTAL_CHARS,
) -> dict[str, Any]:
    """Collect relevant source evidence under strict file and token budgets.

    Explicit defect locations win. Their direct Python import neighbours follow.
    A bounded BM25-style lexical search then retrieves related source files
    across supported languages using the task goal and defect descriptions.
    """
    base = Path(root).resolve()
    modules = repo_context.get("modules", [])
    module_list = modules if isinstance(modules, list) else []
    module_to_path = _module_paths(module_list)
    path_to_module = {path: name for name, path in module_to_path.items()}

    ordered: list[str] = []
    for defect in defects:
        if isinstance(defect, dict) and defect.get("file"):
            ordered.append(str(defect["file"]))

    # Add one-hop Python import neighbours for defect files.
    for rel in list(ordered):
        module_name = path_to_module.get(rel)
        if not module_name:
            continue
        info = next(
            (item for item in module_list
             if isinstance(item, dict) and item.get("path") == rel),
            None,
        )
        if not info:
            continue
        for imported in sorted(info.get("imports", [])):
            neighbour = module_to_path.get(str(imported))
            if neighbour:
                ordered.append(neighbour)

    query = " ".join(
        [goal]
        + [
            str(defect.get("description", ""))
            for defect in defects if isinstance(defect, dict)
        ]
    )
    lexical = _lexical_rank(base, query, set(ordered))
    ordered.extend(lexical)

    # For a generic task with no query hits, fall back to the largest Python modules.
    if not ordered and module_list:
        ranked_modules = sorted(
            (item for item in module_list
             if isinstance(item, dict) and item.get("path")),
            key=lambda item: (-int(item.get("loc", 0)), str(item["path"])),
        )
        ordered.extend(str(item["path"]) for item in ranked_modules)

    rendered: list[str] = []
    included: list[str] = []
    total = 0
    seen: set[str] = set()
    truncated = False

    for rel in ordered:
        if rel in seen:
            continue
        seen.add(rel)
        if len(included) >= max_files:
            truncated = True
            break
        target = _safe_relative(base, rel)
        if target is None:
            continue
        try:
            raw = target.read_bytes()
        except OSError:
            continue
        if len(raw) > max_file_bytes:
            truncated = True
            raw = raw[:max_file_bytes]
        try:
            source = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            continue
        remaining = max_total_chars - total
        if remaining <= 0:
            truncated = True
            break
        if len(source) > remaining:
            source = source[:remaining]
            truncated = True
        if not source:
            continue
        rendered.append(f"FILE: {rel}\n{source}")
        included.append(rel)
        total += len(source)
        if total >= max_total_chars:
            truncated = True
            break

    return {
        "files": included,
        "rendered": "\n\n".join(rendered) if rendered else "(No eligible source files were selected.)",
        "truncated": truncated,
        "characters": total,
        "retrieval": "bm25_lexical",
    }
