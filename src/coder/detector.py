"""Defect discovery — stage 2: deterministic static pass + model ranking.

الاكتشاف (مهمة M2.2): الفحص الثابت حتمي (أخطاء صياغة وبقع TODO وسموم
معلومة)، وترتيب الخطورة والاستدلال من النموذج عبر موصل BYOK، والدمج
مستقر وقابل للاختبار بلا شبكة.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
SUSPICIOUS_PATTERNS = (
    ("except Exception: pass", "silent exception swallowing"),
    ("TODO", "unresolved TODO marker"),
    ("FIXME", "unresolved FIXME marker"),
)
MAX_SNIPPET = 200

_PROMPT_TEMPLATE = (
    "You are the defect-discovery stage of a coding agent.\n"
    "Goal: {goal}\n"
    "Repo context: {summary}\n"
    "Static findings: {static}\n"
    "Reply with ONLY a JSON array of objects "
    '{{"file": str, "description": str, "severity": "high"|"medium"|"low"}}.\n'
)


def static_scan(root: Path, *, limit: int = 200) -> list:
    """Deterministic pass: syntax errors + known smelly markers, capped."""
    findings: list = []
    for path in sorted(Path(root).rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if any(part.startswith(".") or part == "__pycache__" for part in Path(rel).parts):
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            ast.parse(source)
        except SyntaxError as exc:
            findings.append({"file": rel, "description": f"syntax error: {exc.msg}",
                             "severity": "high", "source": "static"})
        for pattern, why in SUSPICIOUS_PATTERNS:
            if pattern in source:
                findings.append({"file": rel, "description": why,
                                 "severity": "low", "source": "static"})
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
    """Merge static findings with model-ranked defects (static always kept).

    ``connector`` must expose ``async generate()`` (the BYOK contract); the
    call is awaited directly so the engine can run inside one event loop.
    """
    static = static if static is not None else static_scan(Path(context.get("root", ".")))
    prompt = _PROMPT_TEMPLATE.format(
        goal=goal,
        summary=context.get("summary", ""),
        static=json.dumps([{"file": f["file"], "description": f["description"]}
                           for f in static[:20]], ensure_ascii=False),
    )
    reply = await connector.generate(prompt)
    model_defects: list = []
    if reply.get("ok"):
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
    merged = static + [d for d in model_defects
                       if not any(s["file"] == d["file"] and s["description"] == d["description"]
                                  for s in static)]
    return sorted(merged, key=lambda d: SEVERITY_RANK.get(d["severity"], 3))
