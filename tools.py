"""NovaMind dev tools — run with: python3 tools.py <command>"""
import sys
from pathlib import Path

def fix_registry():
    core = Path("src/novamind/registry/core.py")
    text = core.read_text(encoding="utf-8")
    if "def all_pipeline_ids" not in text:
        text += '''

def all_pipeline_ids() -> list:
    data = load_registry()
    return list(data.get("pipelines", {}).keys())

def all_pipelines() -> dict:
    data = load_registry()
    return dict(data.get("pipelines", {}))

def pipeline(pipeline_id: str):
    data = load_registry()
    return data.get("pipelines", {}).get(pipeline_id)
'''
        core.write_text(text, encoding="utf-8")
        print("✅ core.py updated")
    
    init = Path("src/novamind/registry/__init__.py")
    itext = init.read_text(encoding="utf-8")
    if "all_pipeline_ids" not in itext:
        itext += "\nfrom novamind.registry.core import all_pipeline_ids, all_pipelines, pipeline\n"
        init.write_text(itext, encoding="utf-8")
        print("✅ __init__.py updated")

def check():
    from novamind.registry import load_registry
    data = load_registry()
    print("Pipelines:", list(data.get("pipelines", {}).keys()))
    print("Agents:", len(data.get("agents", {})))

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    funcs = {"fix-registry": fix_registry, "check": check}
    if cmd in funcs:
        funcs[cmd]()
    else:
        print("Commands:", ", ".join(funcs.keys()))
