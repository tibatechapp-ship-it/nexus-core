#!/usr/bin/env python3
"""
يولّد hive/factory/registry_full.py تلقائياً من فحص الوكلاء.
"""
import json
from pathlib import Path

SIG_FILE = Path("/public/reports/all_agents_signatures.json")
OUTPUT = Path("/public/hive/factory/registry_full.py")

# تصنيف الوكلاء
CATEGORIES = {
    "security": ["security_agent", "security_engineer", "auth_agent",
                 "crypto_agent", "secrets_agent", "injection_agent",
                 "xss_agent", "privacy_agent", "compliance_agent"],
    "testing": ["test_generator", "test_runner", "tester", "qa_devops",
                "evaluation_agent"],
    "devops": ["devops_engineer", "docker_agent", "k8s_agent",
               "terraform_agent", "cicd_agent", "nginx_agent",
               "migration_agent", "monitoring_agent"],
    "data": ["sql_agent", "nosql_agent", "orm_agent", "data_scientist",
             "db_migration_agent", "indexing_agent", "embedding_agent",
             "finetune_agent"],
    "ui": ["react_agent", "vue_agent", "css_agent", "a11y_agent",
           "rtl_agent", "api_design_agent"],
    "code": ["coder", "fixer", "multi_fixer", "refactor_agent",
             "code_review_agent", "deadcode_agent", "duplication_agent",
             "complexity_agent", "naming_agent", "performance_agent",
             "dependency_agent", "parallel_agents", "agent_builder"],
    "analysis": ["analyzer", "multilang_analyzer", "arabic_analyzer",
                 "deadcode_agent", "dependency_agent", "complexity_agent",
                 "duplication_agent", "naming_agent", "performance_agent"],
    "architecture": ["architect", "chief_architect", "architecture_agent",
                     "api_design_agent"],
    "documentation": ["documentation_agent", "technical_writer"],
    "management": ["project_manager", "lead_researcher", "senior_engineer",
                   "junior_engineer"],
    "monitoring": ["monitoring_agent"],
    "other": ["learner", "quality_guardian", "git_agent", "transaction_agent",
              "prompt_agent", "javascript_analyzer", "cpp_analyzer"],
}


def get_category(name: str) -> str:
    for cat, names in CATEGORIES.items():
        if name in names:
            return cat
    return "other"


def build_signature_map(method_args: list, is_instance: bool) -> dict:
    """
    يبني signature_map المناسب بناءً على معاملات الدالة.
    - task → code (للـ analyze)
    - task → request (للـ build)
    - task → code (للـ fix)
    - ctx.filename → filename
    """
    smap: dict[str, Any] = {}

    if not method_args:
        return smap

    # حالة 1: analyze(code, filename)
    if "code" in method_args:
        smap["task"] = "code"
        if "filename" in method_args:
            smap["ctx.filename"] = "filename"

    # حالة 2: handle(task)
    elif "task" in method_args and len(method_args) == 1:
        smap["task"] = "task"

    # حالة 3: build(request)
    elif "request" in method_args:
        smap["task"] = "request"

    # حالة 4: fix(code, error, ...)
    elif "code" in method_args and "error" in method_args:
        smap["task"] = "code"
        smap["ctx.error"] = "error"
        if "issues" in method_args:
            smap["ctx.issues"] = "issues"

    # حالة 5: learn(summary, ...)
    elif "summary" in method_args:
        smap["task"] = "summary"

    # حالة 6: run(code, timeout)
    elif "code" in method_args:
        smap["task"] = "code"

    # حالة 7: detect_lang(filename)
    elif "filename" in method_args and len(method_args) == 1:
        smap["ctx.filename"] = "filename"

    # حالة 8: run_pytest(test_code, ...)
    elif "test_code" in method_args:
        smap["task"] = "test_code"

    # حالة 9: evaluate(candidate, criteria)
    elif "candidate" in method_args:
        smap["task"] = "candidate"

    return smap


def main():
    with open(SIG_FILE) as f:
        data = json.load(f)

    agents = data["agents"]

    # ابدأ بناء الملف
    lines = [
        '#!/usr/bin/env python3',
        '"""',
        'Hive Factory Registry — Full (67 Agents)',
        '==========================================',
        'يولّد تلقائياً من reports/all_agents_signatures.json',
        f'عدد الوكلاء: {len(agents)}',
        '"""',
        'from __future__ import annotations',
        '',
        'from dataclasses import dataclass, field',
        'from typing import Dict, List, Optional, Any',
        'import logging',
        '',
        'logger = logging.getLogger("hive.factory.registry_full")',
        '',
        '',
        '@dataclass',
        'class AgentSpec:',
        '    """مواصفات وكيل واحد."""',
        '    name: str',
        '    category: str',
        '    module: str',
        '    class_name: str',
        '    method: str',
        '    timeout_seconds: int = 120',
        '    max_cost_usd: float = 0.10',
        '    signature_map: Dict[str, str] = field(default_factory=dict)',
        '',
        '',
        '# ═══════════════════════════════════════════════════════════════',
        f'# AGENT_REGISTRY — {len(agents)} وكيل',
        '# ═══════════════════════════════════════════════════════════════',
        'AGENT_REGISTRY: Dict[str, AgentSpec] = {',
        '',
    ]

    for a in agents:
        name = a["name"]
        category = get_category(name)
        module = a["module"]
        class_name = a["class_name"]
        method = a["method"]
        smap = build_signature_map(a.get("method_args", []), a.get("use_instance", False))

        lines.append(f'    "{name}": AgentSpec(')
        lines.append(f'        name="{name}",')
        lines.append(f'        category="{category}",')
        lines.append(f'        module="{module}",')
        lines.append(f'        class_name="{class_name}",')
        lines.append(f'        method="{method}",')
        if smap:
            lines.append(f'        signature_map={smap!r},')
        lines.append('    ),')
        lines.append('')

    lines.extend([
        '}',
        '',
        '',
        '# ═══════════════════════════════════════════════════════════════',
        '# Stats',
        '# ═══════════════════════════════════════════════════════════════',
        'def get_stats() -> Dict[str, Any]:',
        '    """إحصائيات السجل."""',
        '    by_cat: Dict[str, int] = {}',
        '    for spec in AGENT_REGISTRY.values():',
        '        by_cat[spec.category] = by_cat.get(spec.category, 0) + 1',
        '    return {',
        '        "total": len(AGENT_REGISTRY),',
        '        "categories": len(by_cat),',
        '        "by_category": by_cat,',
        '    }',
        '',
        '',
        'if __name__ == "__main__":',
        '    import json',
        '    print("=" * 70)',
        f'    print("📋 Full Registry — {len(agents)} وكيل")',
        '    print("=" * 70)',
        '    stats = get_stats()',
        '    print(f"\\n📊 إجمالي: {stats[\'total\']}")',
        '    print(f"📁 الفئات: {stats[\'categories\']}\\n")',
        '    for cat, count in sorted(stats["by_category"].items()):',
        '        print(f"   • {cat:20s}: {count}")',
    ])

    # اكتب الملف
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ تم إنشاء: {OUTPUT}")
    print(f"   📊 عدد الوكلاء: {len(agents)}")
    print(f"   📏 الحجم: {len(chr(10).join(lines))} حرف")


if __name__ == "__main__":
    main()
