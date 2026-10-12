#!/usr/bin/env python3
"""NovaMind-Hive Unified CLI."""
import sys
import os
import argparse
import subprocess
import importlib
import inspect
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _load_env():
    for env_name in [PROJECT_ROOT / ".env", PROJECT_ROOT / ".vault" / "secrets.env"]:
        if env_name.exists():
            for line in env_name.read_text(encoding="utf-8").split("\n"):
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")


def cmd_status():
    _load_env()
    print("=" * 60)
    print("NovaMind-Hive System Status")
    print("=" * 60)
    
    agents_dir = PROJECT_ROOT / "nova" / "agents"
    all_py = [f for f in agents_dir.glob("*.py")
              if f.name != "__init__.py"
              and not f.name.startswith("_")
              and ".bak" not in f.name]
    print(f"  Agents:      {len(all_py)} files")
    
    instances = 0
    for f in all_py:
        try:
            mod = importlib.import_module(f"nova.agents.{f.stem}")
            for attr in dir(mod):
                if attr.startswith("_"):
                    continue
                obj = getattr(mod, attr)
                if inspect.isclass(obj) or inspect.ismodule(obj) or callable(obj):
                    continue
                if attr in ("logger", "logging", "log"):
                    continue
                instances += 1
                break
        except Exception:
            pass
    print(f"  Instances:   {instances} agents")
    
    try:
        from config import settings
        print(f"  Settings:    env={settings.app_env}")
        print(f"  Host:        {settings.host}:{settings.port}")
    except Exception as e:
        print(f"  Settings:    ERROR {type(e).__name__}")


def cmd_agents():
    _load_env()
    agents_dir = PROJECT_ROOT / "nova" / "agents"
    all_py = sorted([f for f in agents_dir.glob("*.py")
                     if f.name != "__init__.py"
                     and not f.name.startswith("_")
                     and ".bak" not in f.name])
    
    print("=" * 78)
    print(f"Registered Agents ({len(all_py)})")
    print("=" * 78)
    
    for f in all_py:
        try:
            mod = importlib.import_module(f"nova.agents.{f.stem}")
            inst_name = None
            for attr in dir(mod):
                if attr.startswith("_"):
                    continue
                obj = getattr(mod, attr)
                if inspect.isclass(obj) or inspect.ismodule(obj) or callable(obj):
                    continue
                if attr in ("logger", "logging", "log"):
                    continue
                inst_name = attr
                break
            status = "[OK]" if inst_name else "[--]"
            print(f"   {status} {f.stem:24s} {inst_name or '(no instance)'}")
        except Exception as e:
            print(f"   [XX] {f.stem:24s} {type(e).__name__}")


def cmd_scan_security():
    _load_env()
    print("Running Security Scan...")
    try:
        from novamind.agents.secret_scanner import SecretScanner
        scanner = SecretScanner(root=str(PROJECT_ROOT))
        result = scanner.scan(target_dir="nova")
        print()
        print(f"  Files scanned:  {result.files_scanned}")
        print(f"  Findings:       {len(result.findings)}")
        print(f"  Elapsed:        {result.elapsed:.2f}s")
        if result.findings:
            for f in result.findings[:10]:
                rel = f.file.relative_to(PROJECT_ROOT)
                print(f"    [{f.severity}] {f.description}")
                print(f"      {rel}:{f.line}")
        else:
            print("  Clean - no secrets found")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")


def cmd_cleanup(execute: bool):
    _load_env()
    mode = "EXECUTE" if execute else "DRY-RUN"
    print(f"Cleanup [{mode}]")
    try:
        from novamind.agents.cleanup_agent import CleanupAgent
        agent = CleanupAgent(root=str(PROJECT_ROOT), dry_run=not execute)
        result = agent.cleanup()
        print(result.report)
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")


def cmd_test():
    _load_env()
    print("Running Agent Test Suite...")
    harness = PROJECT_ROOT / "tests" / "test_all_agents_unified.py"
    if not harness.exists():
        print(f"  ERROR: {harness} not found")
        return 1
    return subprocess.run([sys.executable, str(harness)]).returncode


def main():
    parser = argparse.ArgumentParser(prog="nova", description="NovaMind-Hive Control Center")
    sub = parser.add_subparsers(dest="command")
    
    sub.add_parser("status", help="Show system status")
    sub.add_parser("agents", help="List all agents")
    sub.add_parser("scan-security", help="Run SecretScanner")
    
    clean_parser = sub.add_parser("cleanup", help="Run CleanupAgent")
    clean_parser.add_argument("--execute", action="store_true", help="Execute (default: dry-run)")
    
    sub.add_parser("test", help="Run agent test harness")
    
    args = parser.parse_args()
    
    if args.command == "status":
        cmd_status()
    elif args.command == "agents":
        cmd_agents()
    elif args.command == "scan-security":
        cmd_scan_security()
    elif args.command == "cleanup":
        cmd_cleanup(execute=args.execute)
    elif args.command == "test":
        return cmd_test()
    else:
        parser.print_help()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
