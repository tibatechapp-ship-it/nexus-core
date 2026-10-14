#!/usr/bin/env python3
import sys, json, time, importlib.util
from pathlib import Path

ROOT = Path('/data/data/com.termux/files/home/nexus-core')
sys.path.insert(0, str(ROOT))
REPORTS = ROOT / 'reports' / 'certification'
REPORTS.mkdir(parents=True, exist_ok=True)

def discover_agents():
    agents = []
    for f in sorted((ROOT / 'src/agents').glob('*.py')):
        if f.name.startswith('_') or f.name in ('base.py', 'factory.py'):
            continue
        agents.append((f.stem, str(f), 'core'))
    for f in sorted((ROOT / 'src/novamind').rglob('*.py')):
        if f.name.startswith('_'):
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
            if isinstance(obj, type) and attr.endswith('Agent') and attr != 'BaseAgent':
                return obj
        return None
    except Exception:
        return None

def smoke_one(name, path, cat):
    r = {'name':name,'category':cat,'path':path,'smoke_status':'UNKNOWN','smoke_response':None,'smoke_error':None}
    try:
        from src.core.zyvo_client import ZyvoBackend
        from src.core.zyvo_client import ZyvoClient; backend = ZyvoBackend(ZyvoClient(host='127.0.0.1', port=4142))
        cls = load_agent_class(name,path)
        if cls is None: r['smoke_status']='NO_CLASS'; return r
        agent = cls(backend)
        resp = agent.run("In one sentence, what is your role?")
        if resp and len(str(resp))>5: r['smoke_status']='PASS'; r['smoke_response']=str(resp)[:200]
        else: r['smoke_status']='EMPTY'
    except Exception as e:
        r['smoke_status']='ERROR'; r['smoke_error']=str(e)[:150]
    return r

def main():
    agents = discover_agents()
    total=len(agents)
    out = REPORTS/'smoke_results.json'
    res=[]
    if out.exists():
        try: res=json.loads(out.read_text())
        except: res=[]
    done={x['name'] for x in res}
    for i,(n,p,c) in enumerate(agents,1):
        if n in done: continue
        res.append(smoke_one(n,p,c))
        if i%10==0: out.write_text(json.dumps(res,indent=2,ensure_ascii=False))
        print(f"[{i}/{total}] {n} -> {res[-1]['smoke_status']}")
    out.write_text(json.dumps(res,indent=2,ensure_ascii=False))
    p=[x for x in res if x['smoke_status']=='PASS']
    print(f"DONE {len(p)}/{len(res)} PASS")

if __name__=='__main__':
    import json
    main()
