#!/usr/bin/env python3
"""
فحص شامل ومحسّن لجميع الوكلاء في nova/agents/
- يتجاهل logger و imports
- يكتشف instances الحقيقية فقط
- يستخرج class + method لكل وكيل
"""
import ast
import json
import re
import sys
from pathlib import Path

# [FIXED PATH] Use relative imports or conftest.py instead
AGENTS_DIR = PROJECT_ROOT = Path(__file__).resolve().parents[3] / "nova" / "agents"
OUTPUT = PROJECT_ROOT = Path(__file__).resolve().parents[3] / "reports" / "all_agents_signatures.json"

# كلمات ممنوعة (ليست وكلاء)
BLACKLIST = {
    "logger", "log", "logging", "os", "sys", "json", "re",
    "asyncio", "time", "datetime", "pathlib", "typing",
    "abc", "dataclass", "field", "ABC", "Enum", "Any",
    "Dict", "List", "Optional", "BaseAgent", "Exception",
}

# أنماط أسماء الوكلاء
AGENT_PATTERNS = [
    r".*_agent$",       # test_agent, security_agent
    r".*er$",           # coder, fixer, analyzer
    r".*or$",           # monitor, manager
    r"^analyzer$",
    r"^coder$",
    r"^fixer$",
    r"^tester$",
    r"^learner$",
    r"^architect$",
    r".*_builder$",
    r".*_writer$",
    r".*_guardian$",
]


def is_agent_name(name: str) -> bool:
    """هل هذا الاسم يشير إلى وكيل؟"""
    if name in BLACKLIST:
        return False
    if name.startswith("_"):
        return False
    lower = name.lower()
    for pattern in AGENT_PATTERNS:
        if re.match(pattern, lower):
            return True
    return False


def analyze_agent_file(path: Path) -> dict:
    """يحلل ملف وكيل واحد."""
    try:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content)
    except Exception as e:
        return {"status": "error", "error": str(e)[:100]}

    # 1. اجمع الـ classes
    classes = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods = []
            for n in node.body:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not n.name.startswith("_"):
                        # استخرج التوقيع
                        args = [a.arg for a in n.args.args if a.arg != "self"]
                        methods.append({
                            "name": n.name,
                            "args": args,
                            "is_async": isinstance(n, ast.AsyncFunctionDef),
                        })
            classes[node.name] = methods

    # 2. ابحث عن instances (مع استثناء logger وما شابه)
    instances = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    name = target.id
                    if name in BLACKLIST:
                        continue
                    if isinstance(node.value, ast.Call):
                        # instance = ClassName()
                        func = node.value.func
                        class_name = None
                        if isinstance(func, ast.Name):
                            class_name = func.id
                        elif isinstance(func, ast.Attribute):
                            class_name = func.attr
                        
                        if class_name and class_name not in BLACKLIST:
                            instances.append({
                                "instance_name": name,
                                "class_name": class_name,
                                "line": node.lineno,
                            })

    return {
        "status": "ok",
        "classes": classes,
        "instances": instances,
        "size": len(content),
    }


def pick_best_agent(result: dict) -> dict:
    """يختار أفضل (instance, class, method) للوكيل."""
    instances = result.get("instances", [])
    classes = result.get("classes", {})

    # أولاً: instance موجود
    for inst in instances:
        if inst["class_name"] in classes:
            methods = classes[inst["class_name"]]
            if methods:
                # اختر أول method (بعد استثناء __init__)
                best_method = methods[0]
                return {
                    "use_instance": True,
                    "class_name": inst["instance_name"],  # اسم الـ instance
                    "actual_class": inst["class_name"],
                    "method": best_method["name"],
                    "method_args": best_method["args"],
                    "is_async": best_method["is_async"],
                }

    # ثانياً: class فقط
    for cls_name, methods in classes.items():
        if cls_name in BLACKLIST:
            continue
        if methods:
            best_method = methods[0]
            return {
                "use_instance": False,
                "class_name": cls_name,
                "actual_class": cls_name,
                "method": best_method["name"],
                "method_args": best_method["args"],
                "is_async": best_method["is_async"],
            }

    return None


def main():
    print("=" * 70)
    print("🔍 فحص محسّن لجميع الوكلاء")
    print("=" * 70)
    print(f"📁 {AGENTS_DIR}")
    print()

    agents = []
    errors = []

    for path in sorted(AGENTS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        if path.name in ["base.py", "factory.py", "__init__.py"]:
            continue

        result = analyze_agent_file(path)
        agent_name = path.stem

        if result["status"] == "error":
            errors.append({"name": agent_name, "error": result["error"]})
            continue

        best = pick_best_agent(result)

        if best:
            agents.append({
                "file": path.name,
                "name": agent_name,
                "module": f"nova.agents.{path.stem}",
                **best,
            })
        else:
            errors.append({"name": agent_name, "error": "لا يوجد class أو instance صالح"})

    # عرض
    print(f"✅ وُجد {len(agents)} وكيل صالح")
    print(f"❌ {len(errors)} خطأ/غير مكتمل")
    print()

    print(f"{'الوكيل':30s} | {'Class/Instance':25s} | {'Method':20s} | {'Args'}")
    print("-" * 100)
    for a in agents:
        cls = a["class_name"]
        method = a["method"]
        args = ",".join(a["method_args"][:3])
        print(f"{a['name']:30s} | {cls:25s} | {method:20s} | {args}")

    if errors:
        print()
        print("❌ الأخطاء:")
        for e in errors[:20]:
            print(f"   • {e['name']}: {e['error']}")

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
