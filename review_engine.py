#!/usr/bin/env python3
"""NovaMind Review Engine — 42 agents"""
import sys
import importlib
import hashlib
import json
import logging
from pathlib import Path
from typing import Dict, List

# [FIXED PATH] Use relative imports or conftest.py instead

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("review_engine")

SEVERITY_WEIGHT = {
    "critical": 15, "high": 8, "medium": 3, "low": 1, "info": 0.5,
}

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


def load_agents(verbose=False):
    """Loads 42 agents with whitelist + hash."""
    agents_dir = Path("/public/agents")
    files = sorted(agents_dir.glob("*_agent.py"))
    hashes = load_hashes()
    loaded = []
    blocked = []
    failed = []

    for f in files:
        name = f.stem.replace("_agent", "")
        if name not in ALLOWED:
            blocked.append(name)
            continue

        fh = compute_hash(f)
        if name in hashes and hashes[name] != fh:
            logger.warning(f"Blocked: {name} (hash mismatch)")
            blocked.append(name)
            continue
        hashes[name] = fh

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
            iface = next(
                (i for i in ("analyze", "review", "scan")
                 if hasattr(inst, i)),
                None,
            )
            if not iface:
                failed.append((name, "no iface"))
                continue

            loaded.append({"name": name, "instance": inst, "iface": iface})
        except Exception as e:
            failed.append((name, str(e)[:50]))

    # Save hashes
    HASHES_FILE.parent.mkdir(parents=True, exist_ok=True)
    HASHES_FILE.write_text(json.dumps(hashes, indent=2))

    if verbose:
        logger.info(f"✅ Loaded: {len(loaded)}")
        if blocked:
            logger.warning(f"🚫 Blocked: {len(blocked)}")
        if failed:
            logger.warning(f"❌ Failed: {len(failed)}")

    return loaded


def review_code(agents, code, filename):
    """Runs all agents on code."""
    issues = []
    for agent in agents:
        try:
            if agent["iface"] == "review":
                result = agent["instance"].review(code, filename)
                agent_issues = result.get("issues", [])
            else:
                result = getattr(agent["instance"], agent["iface"])(code, filename)
                agent_issues = result.get("issues", [])

            for issue in agent_issues:
                issue["agent"] = agent["name"]
                issue["file"] = filename
                issues.append(issue)
        except Exception as e:
            logger.debug(f"Agent {agent['name']} error: {e}")
    return issues


def classify(issues):
    """Classify issues."""
    by_sev = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    by_agent = {}
    for i in issues:
        sev = i.get("severity", "info").lower()
        if sev in by_sev:
            by_sev[sev] += 1
        agent = i.get("agent", "?")
        by_agent[agent] = by_agent.get(agent, 0) + 1

    priority = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    sorted_issues = sorted(
        issues,
        key=lambda x: priority.get(x.get("severity", "info"), 5),
    )

    score = 100
    for i in issues:
        score -= SEVERITY_WEIGHT.get(i.get("severity", "info").lower(), 1)
    score = max(0, int(score))

    return {
        "total": len(issues),
        "score": score,
        "by_severity": by_sev,
        "by_agent": by_agent,
        "top_issues": sorted_issues[:20],
    }


def review_repo(repo, max_files=50, verbose=True):
    """Review GitHub repo."""
    from integration.github_client import github

    if verbose:
        print(f"🔍 Reviewing: {repo}")

    r = github.get_repo(repo)
    if not r.get("ok"):
        return {"ok": False, "repo": repo, "error": r.get("error")}

    repo_data = r["data"]
    branch = repo_data.get("default_branch", "main")

    r = github._request("GET", f"/repos/{repo}/contents?ref={branch}")
    if not r.get("ok"):
        return {"ok": False, "repo": repo, "error": r.get("error")}

    code_exts = (".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs",
                 ".java", ".rb", ".php", ".c", ".cpp", ".cs")
    files = [f for f in r["data"]
             if f.get("type") == "file"
             and f.get("name", "").endswith(code_exts)]

    agents = load_agents(verbose=verbose)
    if verbose:
        print(f"   Loaded {len(agents)} agents")
        print(f"   Found {len(files)} code files")

    all_issues = []
    file_reports = {}

    for f in files[:max_files]:
        content = github.get_file(repo, f["path"], branch=branch)
        if not content.get("ok"):
            continue
        code = content.get("content", "")
        if len(code) < 10:
            continue

        issues = review_code(agents, code, f["path"])
        file_reports[f["path"]] = len(issues)
        all_issues.extend(issues)

        if verbose:
            icon = "✅" if not issues else "⚠️ "
            print(f"   {icon} {f['path']:50s} {len(issues):4d}")

    return {
        "ok": True,
        "repo": repo,
        "files_scanned": len(file_reports),
        "file_reports": file_reports,
        "issues": all_issues,
        **classify(all_issues),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("--max-files", type=int, default=20)
    args = parser.parse_args()

    result = review_repo(args.repo, args.max_files)

    if not result.get("ok"):
        print(f"❌ {result.get('error')}")
        sys.exit(1)

    print()
    print("═" * 60)
    print("  📊 Summary")
    print("═" * 60)
    print(f"  Files:  {result['files_scanned']}")
    print(f"  Issues: {result['total']}")
    print(f"  Score:  {result['score']}/100")
    print()
    for sev, n in result["by_severity"].items():
        if n > 0:
            print(f"  {sev:10s}: {n}")
