#!/usr/bin/env python3
"""
فحص شامل لجميع الوكلاء في nova/agents/
"""
import ast
import json
import inspect
import sys
from pathlib import Path

# [FIXED PATH] Use relative imports or conftest.py instead

# [FIXED PATH] Use relative imports or conftest.py instead
AGENTS_DIR = PROJECT_ROOT / "nova" / "agents"
OUTPUT = PROJECT_ROOT / "reports" / "all_agents_signatures.json"


def analyze_agent_file(path: Path) -> dict:
    """يحلل ملف وكيل واحد ويستخرج: classes, instances, methods."""
    try:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content)
    except Exception as e:
        return {"status": "error", "error": str(e)[:100]}

    # ابحث عن الـ classes
    classes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods = [
                n.name for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not n.name.startswith("_")
            ]
            classes.append({
                "class_name": node.name,
                "methods": methods,
            })

    # ابحث عن الـ instances (متغيرات على مستوى الوحدة)
    # مثال: multilang_analyzer = MultiLangAnalyzer()
    instances = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if isinstance(node.value, ast.Call):
                        # instance = ClassName()
                        instances.append({
                            "instance_name": target.id,
                            "class_name": getattr(node.value.func, 'id', 'unknown'),
                        })

    # ابحث عن الواردات
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    return {
        "status": "ok",
        "classes": classes,
        "instances": instances,
        "imports": imports,
        "size": len(content),
    }


def main():
    print("=" * 70)
    print("🔍 فحص شامل لجميع الوكلاء")
    print("=" * 70)
    print(f"📁 {AGENTS_DIR}")
    print()

    agents = []
    errors = []

    for path in sorted(AGENTS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        if path.name in ["base.py", "factory.py"]:
            continue

        result = analyze_agent_file(path)
        agent_name = path.stem

        if result["status"] == "error":
            errors.append({"name": agent_name, "error": result["error"]})
            continue

        # اختر أفضل class/instance
        class_name = None
        method_name = None

        if result["instances"]:
            # أفضل: instance جاهز
            inst = result["instances"][0]
            class_name = inst["instance_name"]
            # ابحث عن class المطابق واستخرج methods
            for c in result["classes"]:
                if c["class_name"] == inst["class_name"]:
                    if c["methods"]:
                        method_name = c["methods"][0]
                    break
        elif result["classes"]:
            # class فقط
            c = result["classes"][0]
            class_name = c["class_name"]
            if c["methods"]:
                method_name = c["methods"][0]

        agents.append({
            "file": path.name,
            "name": agent_name,
            "class_name": class_name,
            "method": method_name,
            "all_classes": result["classes"],
            "all_instances": result["instances"],
        })

    # عرض النتائج
    print(f"✅ وُجد {len(agents)} وكيل")
    print(f"❌ {len(errors)} خطأ")
    print()

    print("📋 الوكلاء:")
    for a in agents:
        status = "✅" if a["class_name"] and a["method"] else "⚠️"
        print(f"   {status} {a['name']:30s} → {a['class_name']}.{a['method']}()")

    # حفظ
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump({
            "total": len(agents),
            "errors": len(errors),
            "agents": agents,
            "error_details": errors,
        }, f, ensure_ascii=False, indent=2)

    print()
    print(f"💾 محفوظ في: {OUTPUT}")


if __name__ == "__main__":
    main()
