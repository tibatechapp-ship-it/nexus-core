#!/usr/bin/env python3
"""Secure Agents Loader v2 — with ops agents"""
import sys
import importlib
import hashlib
import json
import logging
from pathlib import Path

# [FIXED PATH] Use relative imports or conftest.py instead

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("secure_load")

# ═══ Whitelist ═══
ALLOWED = {
    "a11y", "api_design", "architecture", "auth", "cicd",
    "code_review", "complexity", "compliance", "crypto", "css",
    "db_migration", "deadcode", "dependency", "docker",
    "documentation", "duplication", "embedding", "evaluation",
    "finetune", "indexing", "injection", "k8s", "migration",
    "monitoring", "naming", "nginx", "nosql", "orm", "performance",
    "privacy", "prompt", "react", "refactor", "rtl", "secrets",
    "security", "sql", "terraform", "transaction", "vue", "xss",
}

# ═══ Ops agents (not analyzers) ═══
OPS_AGENTS = {"git"}  # git has status/commit/push, not analyze

HASHES_FILE = Path("/public/memory/agent_hashes.json")


def compute_hash(fp):
    return hashlib.sha256(fp.read_bytes()).hexdigest()


def load_hashes():
    if not HASHES_FILE.exists():
        return {}
    try:
        return json.loads(HASHES_FILE.read_text())
    except Exception:
        return {}


def save_hashes(h):
    HASHES_FILE.parent.mkdir(parents=True, exist_ok=True)
    HASHES_FILE.write_text(json.dumps(h, indent=2))


def load_all_agents(verbose=True):
    agents_dir = Path("/public/agents")
    files = sorted(agents_dir.glob("*_agent.py"))
    hashes = load_hashes()

    analyzers = []
    ops = []
    blocked = []
    failed = []

    for f in files:
        name = f.stem.replace("_agent", "")

        # Whitelist
        if name not in ALLOWED and name not in OPS_AGENTS:
            blocked.append(name)
            continue

        # Hash
        fh = compute_hash(f)
        if name in hashes and hashes[name] != fh:
            logger.warning(f"Blocked: {name} (hash mismatch)")
            blocked.append(name)
            continue
        hashes[name] = fh

        # Load
        try:
            mod = importlib.import_module(f"agents.{f.stem}")
            cls = None
            for attr in dir(mod):
                obj = getattr(mod, attr)
                if (isinstance(obj, type) and attr.endswith("Agent")
                        and attr != "BaseAgent"):
                    cls = obj
                    break
            if not cls:
                failed.append((name, "no class"))
                continue

            inst = cls()

            # Ops agent?
            if name in OPS_AGENTS:
                ops.append({"name": name, "instance": inst})
                continue

            # Analyzer
            iface = next(
                (i for i in ("analyze", "review", "scan")
                 if hasattr(inst, i)),
                None,
            )
            if not iface:
                failed.append((name, "no iface"))
                continue

            analyzers.append({"name": name, "instance": inst, "iface": iface})
        except Exception as e:
            failed.append((name, str(e)[:50]))
            logger.error(f"Failed: {name} — {e}")

    save_hashes(hashes)

    if verbose:
        logger.info(f"✅ Analyzers: {len(analyzers)}")
        logger.info(f"⚙️  Ops:       {len(ops)}")
        if blocked:
            logger.warning(f"🚫 Blocked:   {len(blocked)}")
        if failed:
            logger.warning(f"❌ Failed:    {len(failed)}")
            for n, e in failed[:5]:
                logger.warning(f"   - {n}: {e}")

    return {"analyzers": analyzers, "ops": ops, "failed": failed}


if __name__ == "__main__":
    result = load_all_agents()
    print()
    print(f"✅ Analyzers: {len(result['analyzers'])}")
    print(f"⚙️  Ops:       {len(result['ops'])}")
    print(f"❌ Failed:    {len(result['failed'])}")
    print()
    for a in result["analyzers"][:5]:
        print(f"   • {a['name']:20s} [{a['iface']}]")
    for o in result["ops"]:
        print(f"   ⚙️  {o['name']:20s} [ops]")
