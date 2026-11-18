"""Defect discovery: deterministic multi-language scan plus model ranking.

The static pass is read-only, bounded and language-aware. Python syntax is
checked with ast; portable security/code-quality signals are detected without
executing repository code. Model findings are ranked separately and never
replace deterministic evidence.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
MAX_SNIPPET = 200
MAX_SOURCE_BYTES = 512 * 1024
SOURCE_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".go", ".rs", ".java", ".kt", ".kts", ".php", ".rb", ".cs",
    ".swift", ".dart", ".vue", ".sql",
}
SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules", "dist",
    "build", ".next", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "vendor", "target", "coverage",
}
SENSITIVE_DIRS = {
    ".env", "secrets", "secret", "credentials", "credential", "private",
}

# Descriptions remain stable for downstream reports and historical tests.
# Findings never contain matched source snippets or credential values.
_LINE_RULES = (
    (re.compile(r"except\s+Exception\s*:\s*pass"), "silent exception swallowing", "low", "silent-exception"),
    (re.compile(r"\bTODO\b"), "unresolved TODO marker", "low", "todo"),
    (re.compile(r"\bFIXME\b"), "unresolved FIXME marker", "low", "fixme"),
    (re.compile(r"\bXXX\b"), "unresolved XXX marker", "low", "xxx"),
    (
        re.compile(
            r"(?:\bverify\s*=\s*False\b|"
            r"\brejectUnauthorized\s*:\s*False\b|"
            r"\bInsecureSkipVerify\s*:\s*true\b|"
            r"CURLOPT_SSL_VERIFYPEER\s*,\s*0)",
            re.IGNORECASE,
        ),
        "TLS certificate verification disabled",
        "high",
        "tls-verification-disabled",
    ),
    (
        re.compile(r"(?:\beval\s*\(|\bnew\s+Function\s*\()"),
        "dynamic code evaluation",
        "medium",
        "dynamic-evaluation",
    ),
    (
        re.compile(r"\b(?:shell\s*=\s*True|child_process\s*\.\s*exec\s*\()"),
        "shell command execution requires input validation",
        "medium",
        "shell-execution",
    ),
    (
        re.compile(
            r"""\b(?:api[_-]?key|secret|password|access[_-]?token)\b"""
            r"""\s*[:=]\s*["'][^"']{8,}["']""",
            re.IGNORECASE,
        ),
        "possible hardcoded credential (value redacted)",
        "medium",
        "hardcoded-credential",
    ),
)

_PROMPT_TEMPLATE = (
    "You are the defect-discovery stage of a coding agent.\n"
    "Goal: {goal}\n"
    "Repo context: {summary}\n"
    "Static findings: {static}\n"
    "Reply with ONLY a JSON array of objects "
    '{{"file": str, "description": str, "severity": "high"|"medium"|"low"}}.\n'
)


def _ignored(path: Path) -> bool:
    """Return True for generated, hidden or sensitive repository paths."""
    return any(
        part in SKIP_DIRS
        or part.lower() in SENSITIVE_DIRS
        or part.startswith(".")
        for part in path.parts
    )


def _finding(path: str, line: int, description: str, severity: str, rule: str) -> dict:
    """Create a stable finding without embedding source snippets or secrets."""
    return {
        "file": path,
        "line": line,
        "description": description,
        "severity": severity,
        "source": "static",
        "rule_id": rule,
    }


def static_scan(root: Path, *, limit: int = 200) -> list:
    """Scan supported source files without executing them; results are bounded.

    Only Python syntax is parsed. Other languages receive conservative,
    line-oriented checks so unsupported syntax is never misreported as broken.
    Symlinks, hidden/generated directories and sensitive paths are excluded.
    """
    if limit <= 0:
        return []
    base = Path(root).resolve()
    findings: list[dict[str, Any]] = []
    for path in sorted(base.rglob("*")):
        if len(findings) >= limit:
            break
        if not path.is_file() or path.is_symlink():
            continue
        try:
            rel_path = path.relative_to(base)
        except ValueError:
            continue
        if _ignored(rel_path) or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        try:
            if path.stat().st_size > MAX_SOURCE_BYTES:
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = rel_path.as_posix()
        if path.suffix.lower() in {".py", ".pyi"}:
            try:
                ast.parse(source)
            except SyntaxError as exc:
                findings.append(
                    _finding(rel, int(exc.lineno or 1), f"syntax error: {exc.msg}",
                             "high", "python-syntax")
                )
                if len(findings) >= limit:
                    break
        for line_number, line in enumerate(source.splitlines(), start=1):
            for pattern, description, severity, rule in _LINE_RULES:
                if pattern.search(line):
                    findings.append(_finding(rel, line_number, description, severity, rule))
                    if len(findings) >= limit:
                        break
            if len(findings) >= limit:
                break
    return findings[:limit]


def _extract_json_array(text: str) -> list:
    """Pull the first JSON array out of a model reply; [] when unparseable."""
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


async def detect(connector: Any, goal: str, context: dict,
                 static: list | None = None) -> list:
    """Merge deterministic findings with model-ranked defects.

    Static findings are always retained, even if the model fails or returns
    malformed data. Model output is treated as untrusted and bounded.
    """
    static = static if static is not None else static_scan(Path(context.get("root", ".")))
    prompt = _PROMPT_TEMPLATE.format(
        goal=goal,
        summary=context.get("summary", ""),
        static=json.dumps(
            [{"file": f["file"], "description": f["description"], "line": f.get("line")}
             for f in static[:20]],
            ensure_ascii=False,
        ),
    )
    reply = await connector.generate(prompt)
    model_defects: list = []
    if isinstance(reply, dict) and reply.get("ok"):
        for raw in _extract_json_array(str(reply.get("reply", ""))):
            if not isinstance(raw, dict) or not raw.get("file"):
                continue
            severity = str(raw.get("severity", "low")).lower()
            model_defects.append({
                "file": str(raw["file"])[:MAX_SNIPPET],
                "description": str(raw.get("description", ""))[:MAX_SNIPPET],
                "severity": severity if severity in SEVERITY_RANK else "low",
                "source": "model",
            })
    merged = static + [
        d for d in model_defects
        if not any(s["file"] == d["file"] and s["description"] == d["description"]
                   for s in static)
    ]
    return sorted(merged, key=lambda d: SEVERITY_RANK.get(d["severity"], 3))
