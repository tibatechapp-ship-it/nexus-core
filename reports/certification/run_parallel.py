#!/usr/bin/env python3
"""Parallel Smoke Test — 3 workers."""
import sys, json, time, importlib.util, threading
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path('/data/data/com.termux/files/home/nexus-core')
sys.path.insert(0, str(ROOT))

REPORTS = ROOT / 'reports' / 'certification'
TIMEOUT_PER_AGENT = 90
WORKERS = 3  # 3 متوازي

# Load existing results to resume
results_file = REPORTS / 'smoke_results.json'
existing = {}
if results_file.exists():
    try:
        for r in json.loads(results_file.read_text()):
            existing[r['name']] = r
    except Exception:
        pass


def discover_agents():
    agents = []
    for f in sorted((ROOT / 'src/agents').glob('*.py')):
        if f.name.startswith('_') or f.name in ('base.py', 'factory.py', 'fixer.py'):
            continue
        agents.append((f.stem, str(f), 'core'))
    for f in sorted((ROOT / 'src/novamind').rglob('*.py')):
        if f.name.startswith('_') or '.safe_' in f.name:
            continue
        stem = f.stem.lower()
        if any(k in stem for k in ['agent', 'worker', 'specialist', 'expert']):
            agents.append((f.stem, str(f), 'novamind'))
    return agents


def load_agent_class(name, path):
    try:
        spec = importlib.util.spec_from_file_location(f"_dyn_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for attr in dir(mod):
            obj = getattr(mod, attr)
            if isinstance(obj, type) and (attr.endswith('Agent') or attr.endswith('Worker')) and attr not in ('BaseAgent',):
                return obj
        return None
    except Exception:
        return None


def test_one(name, path, category):
    r = {'name': name, 'category': category, 'path': path, 'smoke_status': 'UNKNOWN'}
    start = time.time()

    try:

        from src.core.zyvo_client import ZyvoClient, ZyvoBackend
        client = ZyvoClient(host='127.0.0.1', port=4142)
        backend = ZyvoBackend(client)
        cls = load_agent_class(name, path)
        if cls is None:
            r['smoke_status'] = 'NO_CLASS'
            return r
        agent = cls(backend)
        resp = agent.run("In one sentence, what is your role?")
        if resp and hasattr(resp, 'ok') and resp.ok:
            r['smoke_status'] = 'PASS'
            r['smoke_response'] = str(resp.output)[:200]
        elif resp and len(str(resp)) > 5:
            r['smoke_status'] = 'PASS'
            r['smoke_response'] = str(resp)[:200]
        else:
            r['smoke_status'] = 'EMPTY'
        r['smoke_status'] = 'TIMEOUT'
    except Exception as e:
        r['smoke_status'] = 'ERROR'
        r['smoke_error'] = f"{type(e).__name__}: {str(e)[:150]}"
    finally:
        r['duration_s'] = round(time.time() - start, 1)
    return r


def save(results):
    """Save results sorted by original order."""
    results_file.write_text(json.dumps(results, indent=2, ensure_ascii=False))


def main():
    agents = discover_agents()
    # Skip already done
    todo = [(n, p, c) for (n, p, c) in agents if n not in existing]
    print(f"\n{'='*60}")
    print(f"🚀 PARALLEL SMOKE TEST — {WORKERS} workers")
    print(f"   Total: {len(agents)}, Done: {len(existing)}, Todo: {len(todo)}")
    print(f"{'='*60}\n")

    results = list(existing.values())
    lock = threading.Lock()
    counter = [0]

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(test_one, n, p, c): n for (n, p, c) in todo}
        for fut in as_completed(futures):
            r = fut.result()
            with lock:
                counter[0] += 1
                results.append(r)
                print(f"[{counter[0]}/{len(todo)}] {r['name']} → {r['smoke_status']} ({r.get('duration_s', '?')}s)")
                if counter[0] % 5 == 0:
                    save(results)
                    print(f"  💾 Saved checkpoint ({len(results)} total)")

    save(results)

    # Summary
    from collections import Counter
    c = Counter(r['smoke_status'] for r in results)
    print(f"\n{'='*60}")
    print(f"📊 COMPLETE")
    for k, v in sorted(c.items()):
        print(f"  {k}: {v}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
