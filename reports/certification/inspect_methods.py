#!/usr/bin/env python3
"""Inspect method names of NO_RUN_METHOD agents."""
import sys, json, importlib.util
from pathlib import Path

ROOT = Path('/data/data/com.termux/files/home/nexus-core')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

RESULTS = ROOT / 'reports' / 'certification' / 'smoke_results.json'

# طرق محتملة للتنفيذ
CANDIDATE_METHODS = [
    'run', 'generate', 'execute', 'process', 'handle', 'analyze',
    'perform', 'act', 'invoke', 'call', '__call__', 'start',
    'respond', 'complete', 'chat', 'answer', 'solve',
]

def load_module(name, path):
    try:
        spec = importlib.util.spec_from_file_location(f"_i_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"_i_{name}"] = mod
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None

def inspect_agent(name, path):
    mod = load_module(name, path)
    if mod is None:
        return {'name': name, 'error': 'import_failed'}
    # ابحث عن class
    for attr in dir(mod):
        obj = getattr(mod, attr)
        if not isinstance(obj, type):
            continue
        if not any(attr.endswith(s) for s in ('Agent', 'Worker', 'Coder', 'Assistant', 'Bot', 'Specialist', 'Runner', 'Manager')):
            continue
        # افحص الطرق
        methods = [m for m in dir(obj) if not m.startswith('_') and callable(getattr(obj, m, None))]
        candidates = [m for m in CANDIDATE_METHODS if m in methods]
        # ابحث عن كل methods عامة
        public_methods = [m for m in methods if not m.startswith('_') and m not in ('close', 'copy', 'dict', 'json', 'model_dump', 'model_validate')][:15]
        return {
            'name': name,
            'class': attr,
            'candidates': candidates,
            'public_methods': public_methods,
        }
    return {'name': name, 'error': 'no_class'}

def main():
    data = json.loads(RESULTS.read_text())
    targets = [r for r in data if r.get('smoke_status') == 'NO_RUN_METHOD']
    print(f"\n{'='*70}")
    print(f"🔍 تحليل {len(targets)} وكيل NO_RUN_METHOD")
    print(f"{'='*70}\n")

    for r in targets:
        path = r.get('path')
        if not path or not Path(path).exists():
            print(f"• {r['name']}: ⚠️ الملف غير موجود")
            continue
        info = inspect_agent(r['name'], path)
        print(f"• {r['name']} ({info.get('class', '?')})")
        print(f"  Candidates: {info.get('candidates', [])}")
        print(f"  Methods: {info.get('public_methods', [])[:8]}")
        print()

if __name__ == '__main__':
    main()
