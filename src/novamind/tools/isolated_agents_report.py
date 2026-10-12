#!/usr/bin/env python3
"""
Isolated Agents Report — تقرير تشخيصي شامل لكل وكيل معزول
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from typing import Optional

PUBLIC = Path("/public")
OUTPUT_JSON = PUBLIC / "reports" / "isolated_agents_report.json"

AGENT_DIRS = [
    PUBLIC / "nova" / "agents",
    PUBLIC / "hive" / "agents",
    PUBLIC / "hive" / "agents" / "specialists",
    PUBLIC / "agent",
]

EXCLUDE = re.compile(
    r'\.git/|__pycache__/|\.venv/|venv/|'
    r'legacy/|rescue/|backups/|_archive/|'
    r'hive_rescue_|merge_backup_|hive_full_backup_|'
    r'sandboxes/|\.pytest_cache/'
)


def analyze_agent_file(path: Path) -> dict:
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        return {"error": str(e), "path": str(path)}

    lines = content.split("\n")
    total_lines = len(lines)

    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        return {
            "path": str(path.relative_to(PUBLIC)),
            "name": path.stem,
            "status": "SYNTAX_ERROR",
            "error": str(e),
            "lines": total_lines,
        }

    docstring = ast.get_docstring(tree) or ""
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    async_funcs = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)

    local_imports = [
        imp for imp in imports
        if imp and (
            imp.startswith("nova.") or imp.startswith("hive.") or
            imp.startswith("core.") or imp.startswith("agents.")
        )
    ]

    uses_llm = any(
        kw in content.lower() for kw in [
            "llm", "openai", "gemini", "groq", "ollama",
            "mistral", "openrouter", "zai", "chat_completion",
            "make_llm_call", "llm_router"
        ]
    )

    uses_tools = any(
        kw in content for kw in [
            "tool", "Tools", "execute_tool", "call_tool",
            "from hive.tools", "from nova.tools"
        ]
    )

    has_error_handling = any(
        isinstance(node, (ast.Try, ast.ExceptHandler))
        for node in ast.walk(tree)
    )

    todos = [
        line.strip() for line in lines
        if "TODO" in line or "FIXME" in line or "XXX" in line
    ]

    has_async = len(async_funcs) > 0

    method_names = [f.name for f in functions] + [f.name for f in async_funcs]
    standard_methods = {
        "run": "run" in method_names,
        "handle": "handle" in method_names,
        "execute": "execute" in method_names,
        "analyze": "analyze" in method_names,
        "generate": "generate" in method_names,
        "review": "review" in method_names,
        "build": "build" in method_names,
        "fix": "fix" in method_names,
        "test": "test" in method_names,
    }

    if total_lines < 30:
        status = "TOO_SMALL"
    elif not docstring and total_lines < 50:
        status = "NO_DOC"
    elif not classes and not functions:
        status = "EMPTY"
    elif todos:
        status = "HAS_TODOS"
    else:
        status = "OK"

    name_lower = path.stem.lower()
    if any(k in name_lower for k in ["security", "xss", "injection", "crypto", "secret", "auth"]):
        category = "security"
    elif any(k in name_lower for k in ["test", "qa", "tester"]):
        category = "testing"
    elif any(k in name_lower for k in ["devops", "docker", "k8s", "terraform", "cicd", "nginx", "deploy"]):
        category = "devops"
    elif any(k in name_lower for k in ["sql", "nosql", "orm", "data", "migration", "db"]):
        category = "data"
    elif any(k in name_lower for k in ["react", "vue", "css", "a11y", "rtl", "ui"]):
        category = "ui"
    elif any(k in name_lower for k in ["review", "refactor", "fixer", "coder", "code"]):
        category = "code"
    elif any(k in name_lower for k in ["analyzer", "complexity", "deadcode", "duplication", "dependency", "naming", "performance"]):
        category = "analysis"
    elif any(k in name_lower for k in ["architect", "architecture", "design"]):
        category = "architecture"
    elif any(k in name_lower for k in ["doc", "writer", "technical"]):
        category = "documentation"
    elif any(k in name_lower for k in ["monitor", "health", "metric"]):
        category = "monitoring"
    elif any(k in name_lower for k in ["manager", "lead", "project"]):
        category = "management"
    else:
        category = "other"

    if status in ("EMPTY", "TOO_SMALL"):
        verdict = "ARCHIVE"
    elif status == "SYNTAX_ERROR":
        verdict = "BROKEN"
    elif not uses_llm and not uses_tools and not local_imports:
        verdict = "REVIEW"
    elif local_imports and has_error_handling:
        verdict = "ACTIVATE"
    else:
        verdict = "COMPLETE"

    return {
        "path": str(path.relative_to(PUBLIC)),
        "name": path.stem,
        "category": category,
        "status": status,
        "verdict": verdict,
        "lines": total_lines,
        "classes": len(classes),
        "functions": len(functions),
        "async_functions": len(async_funcs),
        "has_async": has_async,
        "has_docstring": bool(docstring),
        "has_error_handling": has_error_handling,
        "uses_llm": uses_llm,
        "uses_tools": uses_tools,
        "local_imports": local_imports,
        "standard_methods": standard_methods,
        "todos_count": len(todos),
        "docstring_preview": docstring[:200] if docstring else "",
    }


def main():
    print("=" * 70)
    print("Isolated Agents Report — تشخيص شامل")
    print("=" * 70)
    print(f"التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    all_agents = []
    for agent_dir in AGENT_DIRS:
        if not agent_dir.exists():
            continue
        for f in agent_dir.rglob("*.py"):
            if EXCLUDE.search(str(f)):
                continue
            if f.name == "__init__.py":
                continue
            all_agents.append(f)

    print(f"عُثر على {len(all_agents)} ملف وكيل\n")

    reports = []
    for f in all_agents:
        report = analyze_agent_file(f)
        reports.append(report)

    by_verdict = defaultdict(list)
    for r in reports:
        if "error" in r or r.get("status") == "SYNTAX_ERROR":
            by_verdict["BROKEN"].append(r)
        else:
            by_verdict[r.get("verdict", "UNKNOWN")].append(r)

    print("=" * 70)
    print("توزيع القرارات")
    print("=" * 70)
    for verdict in ["ACTIVATE", "COMPLETE", "REVIEW", "ARCHIVE", "BROKEN"]:
        count = len(by_verdict[verdict])
        if count:
            icon = {
                "ACTIVATE": "[+]",
                "COMPLETE": "[~]",
                "REVIEW": "[?]",
                "ARCHIVE": "[-]",
                "BROKEN": "[!]",
            }[verdict]
            print(f"   {icon} {verdict:10s}: {count} وكيل")

    for verdict in ["ACTIVATE", "COMPLETE", "REVIEW", "ARCHIVE", "BROKEN"]:
        items = by_verdict[verdict]
        if not items:
            continue

        print()
        print("=" * 70)
        print(f"{verdict} — {len(items)} وكيل")
        print("=" * 70)

        for r in items[:30]:
            name = r.get("name", "?")
            lines = r.get("lines", 0)
            cat = r.get("category", "?")
            print(f"   - {name:30s} [{cat:12s}] {lines:4d} سطر")

        if len(items) > 30:
            print(f"   ... و {len(items) - 30} آخرين")

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "total": len(reports),
            "by_verdict": {k: len(v) for k, v in by_verdict.items()},
            "agents": reports,
        }, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 70)
    print(f"التقرير الكامل محفوظ في: {OUTPUT_JSON}")
    print("=" * 70)

    print()
    print("التوصيات:")
    print(f"   [+] فعّل ({len(by_verdict['ACTIVATE'])}) وكيلاً فوراً")
    print(f"   [~] أكمل ({len(by_verdict['COMPLETE'])}) وكيلاً ناقصاً")
    print(f"   [?] راجع ({len(by_verdict['REVIEW'])}) وكيلاً يدوياً")
    print(f"   [-] أرشف ({len(by_verdict['ARCHIVE'])}) وكيلاً غير مفيد")
    if by_verdict["BROKEN"]:
        print(f"   [!] أصلح ({len(by_verdict['BROKEN'])}) وكيلاً مكسوراً")


if __name__ == "__main__":
    main()
