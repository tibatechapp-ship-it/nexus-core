"""
NovaMind Bootstrap — سكريبت واحد يرتب المشروع تلقائياً.
Version: 1.0.0
Usage: python3 bootstrap.py [--dry-run] [--force] [--step N]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ═══════════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════════

ROOT = Path("/public")
SRC = ROOT / "src" / "novamind"
STATE_FILE = ROOT / ".bootstrap_state.json"

LEGACY_DIRS = ["nova", "hive"]
LEGACY_ROOT_FILES = [
    "registry.py",
    "unified_agent.py",
    "novamind.py",
    "ci_auto_fixer.py",
    "_aliases.py",
    "_fixtures.py",
    "_init_databases.py",
]
BACKUP_PATTERNS = [
    "*.before_*",
    "*_backup.py",
    "*.bak",
    "*.orig",
]

MOVE_MAP = {
    "nova/_registry": "src/novamind/registry",
    "nova/agents": "src/novamind/agents",
    "nova/core": "src/novamind/core",
    "nova/eval": "src/novamind/eval",
    "nova/security": "src/novamind/security",
    "nova/dashboard": "src/novamind/dashboard",
    "nova/cli": "src/novamind/cli",
    "nova/tools": "src/novamind/tools",
    "nova/scripts": "scripts",
    "nova/tests": "tests/_legacy_nova",
    "hive": "src/novamind/core/hive",
}

# ═══════════════════════════════════════════════════════════════════
#  STATE
# ═══════════════════════════════════════════════════════════════════

@dataclass
class State:
    version: str = "1.0.0"
    last_step: int = 0
    completed: list[str] = field(default_factory=list)
    backups: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "State":
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return cls(**data)
        return cls()

    def save(self) -> None:
        STATE_FILE.write_text(
            json.dumps(self.__dict__, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

# ═══════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════

def run(cmd: list[str], check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(
        cmd, check=check, capture_output=capture, text=True, cwd=ROOT
    )

def git_clean() -> bool:
    r = run(["git", "status", "--porcelain"], check=False)
    return not r.stdout.strip()

def git_branch() -> str:
    r = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], check=False)
    return r.stdout.strip()

def git_commit_all(msg: str) -> None:
    run(["git", "add", "-A"])
    run(["git", "commit", "-m", msg], check=False)

def git_backup_tag(name: str) -> None:
    tag = f"bootstrap-backup-{name}"
    run(["git", "tag", "-f", tag], check=False)

def banner(text: str) -> None:
    print()
    print("═" * 70)
    print(f"  {text}")
    print("═" * 70)

# ═══════════════════════════════════════════════════════════════════
#  STEPS
# ═══════════════════════════════════════════════════════════════════

def step_00_preflight(state: State, dry: bool) -> None:
    banner("STEP 0 — Preflight")

    branch = git_branch()
    print(f"  Branch: {branch}")

    if not git_clean():
        print("  ⚠️  Working tree not clean")
        if not dry:
            print("  → Stashing changes")
            run(["git", "stash", "push", "-m", "bootstrap-preflight"], check=False)
    else:
        print("  ✅ Working tree clean")

    # Backup tag
    if not dry:
        git_backup_tag(state.version)
    print(f"  ✅ Backup tag: bootstrap-backup-{state.version}")

    state.completed.append("preflight")


def step_01_detect(state: State, dry: bool) -> dict[str, Any]:
    banner("STEP 1 — Detect project layout")

    layout: dict[str, Any] = {
        "has_nova": (ROOT / "nova").exists(),
        "has_hive": (ROOT / "hive").exists(),
        "has_src": SRC.exists(),
        "has_pyproject": (ROOT / "pyproject.toml").exists(),
        "has_pytest_ini": (ROOT / "pytest.ini").exists(),
        "has_tests": (ROOT / "tests").exists(),
        "backups": [],
    }

    for pat in BACKUP_PATTERNS:
        layout["backups"].extend(
            str(p.relative_to(ROOT)) for p in ROOT.rglob(pat)
            if ".git" not in str(p) and "venv" not in str(p)
        )

    print(f"  nova/       : {layout['has_nova']}")
    print(f"  hive/       : {layout['has_hive']}")
    print(f"  src/novamind/: {layout['has_src']}")
    print(f"  pyproject   : {layout['has_pyproject']}")
    print(f"  pytest.ini  : {layout['has_pytest_ini']}")
    print(f"  tests/      : {layout['has_tests']}")
    print(f"  backups     : {len(layout['backups'])} files")

    state.completed.append("detect")
    return layout


def step_02_cleanup_backups(state: State, dry: bool) -> None:
    banner("STEP 2 — Clean backup files")

    removed = 0
    for pat in BACKUP_PATTERNS:
        for p in ROOT.rglob(pat):
            if ".git" in str(p) or "venv" in str(p):
                continue
            print(f"  - {p.relative_to(ROOT)}")
            if not dry:
                p.unlink()
            removed += 1

    print(f"  {'Would remove' if dry else 'Removed'}: {removed} files")
    state.completed.append("cleanup_backups")


def step_03_scaffold_src(state: State, dry: bool) -> None:
    banner("STEP 3 — Scaffold src/novamind/")

    if SRC.exists():
        print("  ✅ Already exists, skipping")
        state.completed.append("scaffold_src")
        return

    subdirs = [
        SRC,
        SRC / "registry",
        SRC / "agents",
        SRC / "core",
        SRC / "eval",
        SRC / "cli",
        SRC / "security",
        SRC / "observability",
        SRC / "utils",
    ]

    for d in subdirs:
        print(f"  + {d.relative_to(ROOT)}")
        if not dry:
            d.mkdir(parents=True, exist_ok=True)
            (d / "__init__.py").touch()

    if not dry:
        (SRC / "__init__.py").write_text(
            '"""NovaMind — unified intelligent agent system."""\n'
            '__version__ = "3.0.0"\n',
            encoding="utf-8",
        )

    state.completed.append("scaffold_src")


def step_04_migrate_dirs(state: State, dry: bool) -> None:
    banner("STEP 4 — Migrate legacy dirs → src/novamind/")

    for src_rel, dst_rel in MOVE_MAP.items():
        src = ROOT / src_rel
        dst = ROOT / dst_rel

        if not src.exists():
            print(f"  ⏭  {src_rel} (not found)")
            continue

        if dst.exists():
            print(f"  ⏭  {dst_rel} (already exists)")
            continue

        print(f"  → {src_rel} → {dst_rel}")
        if not dry:
            dst.parent.mkdir(parents=True, exist_ok=True)
            run(["git", "mv", src_rel, dst_rel], check=False)

    state.completed.append("migrate_dirs")


def step_05_fix_imports(state: State, dry: bool) -> None:
    banner("STEP 5 — Fix imports")

    if not SRC.exists():
        print("  ⚠️  src/novamind/ does not exist, skipping")
        state.completed.append("fix_imports")
        return

    replacements = [
        ("from nova._registry", "from novamind.registry"),
        ("from nova.agents", "from novamind.agents"),
        ("from nova.core", "from novamind.core"),
        ("from nova.security", "from novamind.security"),
        ("from nova.eval", "from novamind.eval"),
        ("from nova.", "from novamind."),
        ("import nova.", "import novamind."),
        ("from hive.", "from novamind.core.hive."),
        ("import hive.", "import novamind.core.hive."),
    ]

    changed = 0
    for py in SRC.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        original = text
        for old, new in replacements:
            text = text.replace(old, new)
        if text != original:
            print(f"  ~ {py.relative_to(ROOT)}")
            if not dry:
                py.write_text(text, encoding="utf-8")
            changed += 1

    print(f"  {'Would update' if dry else 'Updated'}: {changed} files")
    state.completed.append("fix_imports")

def step_06_verify(state: State, dry: bool) -> bool:
    banner("STEP 6 — Verify (run tests)")

    if dry:
        print("  [dry-run] skip")
        return True

    r = run(
        ["python3", "-m", "pytest", "-q", "--tb=line", "-x"],
        check=False,
    )
    ok = r.returncode == 0

    if ok:
        print("  ✅ Tests pass")
        state.completed.append("verify")
    else:
        print("  ❌ Tests failed")
        print(r.stdout[-2000:])
        print(r.stderr[-1000:])

    return ok


def step_07_report(state: State, layout: dict[str, Any]) -> None:
    banner("STEP 7 — Final report")

    print(f"  Branch      : {git_branch()}")
    print(f"  Last commit : ", end="")
    r = run(["git", "log", "--oneline", "-1"], check=False)
    print(r.stdout.strip())

    print(f"  src/novamind: {'✅' if SRC.exists() else '❌'}")
    print(f"  pyproject   : {'✅' if (ROOT / 'pyproject.toml').exists() else '❌'}")
    print(f"  pytest.ini  : {'✅' if (ROOT / 'pytest.ini').exists() else '❌'}")
    print(f"  Makefile    : {'✅' if (ROOT / 'Makefile').exists() else '❌'}")

    print()
    print("  Completed steps:")
    for s in state.completed:
        print(f"    ✅ {s}")

    print()
    print("  Next steps:")
    print("    1. pip install -e '.[dev]'")
    print("    2. make test")
    print("    3. make lint")
    print("    4. git push origin <branch>")


# ═══════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════

STEPS = [
    ("preflight",       step_00_preflight),
    ("detect",          step_01_detect),
    ("cleanup_backups", step_02_cleanup_backups),
    ("scaffold_src",    step_03_scaffold_src),
    ("migrate_dirs",    step_04_migrate_dirs),
    ("fix_imports",     step_05_fix_imports),
    ("verify",          step_06_verify),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="NovaMind bootstrap")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--step", type=int, default=None, help="Run single step N")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    state = State.load() if args.resume else State()

    banner(f"NovaMind Bootstrap v{state.version}")
    print(f"  Mode       : {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print(f"  Root       : {ROOT}")
    print(f"  Resume     : {args.resume}")

    layout: dict[str, Any] = {}

    for i, (name, fn) in enumerate(STEPS):
        if args.step is not None and i != args.step:
            continue
        if args.resume and name in state.completed:
            print(f"  ⏭  {name} (done)")
            continue

        state.last_step = i
        result = fn(state, args.dry_run)

        if name == "detect":
            layout = result
        elif name == "verify" and result is False:
            print("  ⚠️  Verification failed")
            if not args.force:
                print("  Use --force to continue anyway")
                state.save()
                return 1

        state.save()

    step_07_report(state, layout)

    banner("Bootstrap complete ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
