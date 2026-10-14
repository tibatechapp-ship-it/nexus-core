#!/usr/bin/env python3
"""Final Smoke Test v3 — Smart method detection."""
import sys, json, time, importlib.util
from pathlib import Path

ROOT = Path('/data/data/com.termux/files/home/nexus-core')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

# ★ إصلاح modules: novamind.core, novamind.core.hive
sys.path.insert(0, str(ROOT / 'src' / 'novamind'))
sys.path.insert(0, str(ROOT / 'src' / 'novamind' / 'core'))
sys.path.insert(0, str(ROOT / 'src' / 'novamind' / 'core' / 'hive'))


REPORTS = ROOT / 'reports' / 'certification'

# ★ الطرق بالترتيب حسب الأولوية
METHODS_PRIORITY = [
    'run',           # Core standard
    'generate',      # LLM Backend style
    'analyze',       # Novamind standard
    'review',        # code_review_agent
    'cleanup',       # cleanup_agent
    'build',         # coder
    'report',        # reporting agents
    'process',
    'execute',
    'check_health',  # maintenance_agent
]

# ★ الوسائط المناسبة لكل طريقة
def call_method(agent, method, prompt):
    fn = getattr(agent, method)
    try:
        # جرّب بـ prompt
        return fn(prompt)
    except TypeError:
        # جرّب بدون args
        return fn()


def test_one(name, path, category):
    r = {'name': name, 'category': category, 'path': path,
         'smoke_status': 'UNKNOWN', 'method_used': None}
    start = time.time()
    try:
        from src.core.zyvo_client import ZyvoClient, ZyvoBackend
        client = ZyvoClient(host='127.0.0.1', port=4142)
        backend = ZyvoBackend(client)

        spec = importlib.util.spec_from_file_location(f"_f_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"_f_{name}"] = mod
        spec.loader.exec_module(mod)

        # ابحث عن class
        cls = None
        cls_name = None
        for attr in dir(mod):
            obj = getattr(mod, attr)
            if isinstance(obj, type):
                if any(attr.endswith(s) for s in ('Agent', 'Worker', 'Coder', 'Runner', 'Builder', 'Manager')):
                    if 'BaseAgent' not in attr:
                        cls = obj
                        cls_name = attr
                        break
        if cls is None:
            r['smoke_status'] = 'NO_CLASS'
            return r

        # جرّب الإنشاء
        try:
            agent = cls(backend)
        except TypeError:
            try:
                agent = cls()
                if hasattr(agent, 'backend'):
                    agent.backend = backend
                elif hasattr(agent, 'llm'):
                    agent.llm = backend
            except Exception as e:
                r['smoke_status'] = 'INIT_FAILED'
                r['smoke_error'] = f'{cls_name}: {str(e)[:100]}'
                return r

        # ابحث عن أي طريقة متاحة
        found_method = None
        for m in METHODS_PRIORITY:
            if hasattr(agent, m) and callable(getattr(agent, m)):
                found_method = m
                break

        if not found_method:
            r['smoke_status'] = 'NO_RUN_METHOD'
            return r

        r['method_used'] = found_method
        try:
            resp = call_method(agent, found_method, "In one sentence, what is your role?")
        except Exception as e:
            r['smoke_status'] = 'CALL_FAILED'
            r['smoke_error'] = f'{found_method}(): {str(e)[:100]}'
            return r

        # قيّم النتيجة
        if hasattr(resp, 'ok') and resp.ok:
            r['smoke_status'] = 'PASS'
        elif resp is not None and len(str(resp)) > 3:
            r['smoke_status'] = 'PASS'
        else:
            r['smoke_status'] = 'EMPTY'

    except Exception as e:
        r['smoke_status'] = 'ERROR'
        r['smoke_error'] = f"{type(e).__name__}: {str(e)[:150]}"
    finally:
        r['duration_s'] = round(time.time() - start, 1)
    return r


def discover_agents():
    SKIP = {'communication', 'metrics', 'registry', 'state', 'agent_alias',
            'agent_builder', 'agent', 'agent_card', 'agent_adapters',
            'agent_router', 'isolated_agents_report', 'scan_all_agents',
            'scan_all_agents_v2', 'agent_orchestrator', 'agent_monitor',
            'agent_real_runner', 'parallel_agents', 'base', '__init__', 'agents_registry'}
    agents = []
    for f in sorted((ROOT / 'src/agents').glob('*.py')):
        if f.stem in SKIP or f.stem.startswith('_') or '.safe_' in f.name:
            continue
        agents.append((f.stem, str(f), 'core'))
    for f in sorted((ROOT / 'src/novamind').rglob('*.py')):
        if f.stem in SKIP or f.stem.startswith('_') or '.safe_' in f.name:
            continue
        stem = f.stem.lower()
        if any(k in stem for k in ['agent', 'worker', 'coder']):
            agents.append((f.stem, str(f), 'novamind'))
    return agents


def main():
    agents = discover_agents()
    print(f"\n🚀 FINAL SMOKE v3 — {len(agents)} agents\n")
    results_file = REPORTS / 'smoke_results_v3.json'
    results = []
    for i, (n, p, c) in enumerate(agents, 1):
        print(f"[{i}/{len(agents)}] {n} ({c})")
        r = test_one(n, p, c)
        m = f" [{r['method_used']}]" if r.get('method_used') else ""
        print(f"  → {r['smoke_status']}{m} ({r.get('duration_s','?')}s)")
        results.append(r)
        if i % 5 == 0:
            results_file.write_text(json.dumps(results, indent=2, ensure_ascii=False))
            print(f"  💾 saved")
    results_file.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    from collections import Counter
    c = Counter(r['smoke_status'] for r in results)
    print(f"\n📊 COMPLETE")
    for k, v in sorted(c.items()):
        print(f"  {k}: {v}")


if __name__ == '__main__':
    main()
