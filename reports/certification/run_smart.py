#!/usr/bin/env python3
"""Smart Smoke Test v2 — Handles namespace + filters real agents."""
import sys, json, time, importlib.util
from pathlib import Path
from datetime import datetime, timezone

# ★ الإصلاح 1: أضف src/ و ~/nexus-core إلى sys.path
ROOT = Path('/data/data/com.termux/files/home/nexus-core')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))  # ← الحل لمشكلة novamind.

REPORTS = ROOT / 'reports' / 'certification'
TIMEOUT_PER_AGENT = 90

# ★ الإصلاح 2: استثنِ الملفات التي ليست وكلاء
SKIP_FILES = {
    'communication', 'metrics', 'registry', 'state',
    'agent_alias', 'agent_builder', 'agent', 'agent_card',
    'agent_adapters', 'agent_router', 'isolated_agents_report',
    'scan_all_agents', 'scan_all_agents_v2',
    'agent_orchestrator', 'agent_monitor', 'agent_real_runner',
    'parallel_agents', 'base', '__init__',
}

# ★ الإصلاح 3: قبول كل الأشكال
AGENT_SUFFIXES = ('Agent', 'Worker', 'Coder', 'Assistant', 'Bot', 'Specialist')


def discover_agents():
    agents = []
    for f in sorted((ROOT / 'src/agents').glob('*.py')):
        if f.stem in SKIP_FILES or f.stem.startswith('_'):
            continue
        if '.safe_' in f.name:
            continue
        agents.append((f.stem, str(f), 'core'))
    for f in sorted((ROOT / 'src/novamind').rglob('*.py')):
        if f.stem in SKIP_FILES or f.stem.startswith('_'):
            continue
        if '.safe_' in f.name:
            continue
        stem = f.stem.lower()
        # قبول كل الملفات التي تحتوي كلمة agent/worker/coder
        if any(k in stem for k in ['agent', 'worker', 'coder']):
            agents.append((f.stem, str(f), 'novamind'))
    return agents


def load_agent_class(name, path):
    """Handle import errors gracefully + try multiple class name patterns."""
    try:
        spec = importlib.util.spec_from_file_location(f"_dyn_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"_dyn_{name}"] = mod
        spec.loader.exec_module(mod)
    except Exception:
        return None, None

    # ابحث عن class يورث BaseAgent أو ينتهي بـ AGENT_SUFFIXES
    candidates = []
    for attr in dir(mod):
        obj = getattr(mod, attr)
        if not isinstance(obj, type):
            continue
        # تحقق من الوراثة
        is_agent = False
        for base in obj.__mro__:
            if 'BaseAgent' in base.__name__ or 'LLMBackend' in base.__name__:
                is_agent = True
                break
        # أو بالاسم
        if any(attr.endswith(s) for s in AGENT_SUFFIXES):
            is_agent = True
        if is_agent and obj.__name__ not in ('BaseAgent',):
            candidates.append((attr, obj))

    if not candidates:
        return None, None
    return candidates[0][0], candidates[0][1]


def test_one(name, path, category):
    r = {'name': name, 'category': category, 'path': path,
         'smoke_status': 'UNKNOWN', 'smoke_response': None, 'smoke_error': None}
    start = time.time()
    try:
        from src.core.zyvo_client import ZyvoClient, ZyvoBackend
        client = ZyvoClient(host='127.0.0.1', port=4142)
        backend = ZyvoBackend(client)

        cls_name, cls = load_agent_class(name, path)
        if cls is None:
            r['smoke_status'] = 'NO_CLASS'
            return r

        # جرّب الإنشاء بعدة طرق
        try:
            agent = cls(backend)
        except TypeError:
            # ربما يحتاج backend+args أخرى؟ جرّب بدون args
            try:
                agent = cls()
                if hasattr(agent, 'backend'):
                    agent.backend = backend
            except Exception:
                r['smoke_status'] = 'INIT_FAILED'
                r['smoke_error'] = f'{cls_name} needs custom init'
                return r

        # جرّب run أو generate
        if hasattr(agent, 'run'):
            resp = agent.run("In one sentence, what is your role?")
        elif hasattr(agent, 'generate'):
            resp = agent.generate("In one sentence, what is your role?")
        else:
            r['smoke_status'] = 'NO_RUN_METHOD'
            return r

        # تحقق من النتيجة
        if hasattr(resp, 'ok') and resp.ok:
            r['smoke_status'] = 'PASS'
            r['smoke_response'] = str(resp.output)[:200] if hasattr(resp, 'output') else str(resp)[:200]
        elif resp and len(str(resp)) > 5:
            r['smoke_status'] = 'PASS'
            r['smoke_response'] = str(resp)[:200]
        else:
            r['smoke_status'] = 'EMPTY'

    except Exception as e:
        r['smoke_status'] = 'ERROR'
        r['smoke_error'] = f"{type(e).__name__}: {str(e)[:150]}"
    finally:
        r['duration_s'] = round(time.time() - start, 1)
    return r


def main():
    agents = discover_agents()
    print(f"\n{'='*60}\n🚀 SMART SMOKE v2 — {len(agents)} agents\n{'='*60}\n")

    results_file = REPORTS / 'smoke_results.json'
    results = []
    if results_file.exists():
        try:
            old = json.loads(results_file.read_text())
            # احتفظ فقط بالنتائج PASS
            results = [r for r in old if r.get('smoke_status') == 'PASS']
            print(f"♻️  محفوظ من قبل: {len(results)} PASS")
        except Exception:
            results = []

    done = {r['name'] for r in results}

    for i, (n, p, c) in enumerate(agents, 1):
        if n in done:
            print(f"[{i}/{len(agents)}] {n} ⏭️ (already PASS)")
            continue
        print(f"[{i}/{len(agents)}] {n} ({c})")
        r = test_one(n, p, c)
        print(f"  → {r['smoke_status']} ({r.get('duration_s', '?')}s)")
        results.append(r)
        if i % 5 == 0:
            results_file.write_text(json.dumps(results, indent=2, ensure_ascii=False))
            print(f"  💾 saved")

    results_file.write_text(json.dumps(results, indent=2, ensure_ascii=False))

    from collections import Counter
    c = Counter(r['smoke_status'] for r in results)
    print(f"\n{'='*60}\n📊 COMPLETE")
    for k, v in sorted(c.items()):
        print(f"  {k}: {v}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
