#!/usr/bin/env python3
"""Unified Agent Test Harness."""
import sys
import os
import inspect
import asyncio
import importlib
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load env
for env_name in [PROJECT_ROOT / ".env", PROJECT_ROOT / ".vault" / "secrets.env"]:
    if env_name.exists():
        content = env_name.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ[k.strip()] = v.strip().strip('"').strip("'")


@dataclass
class TestResult:
    name: str
    method: str
    status: str
    duration_ms: float
    output_type: Optional[str] = None
    error: Optional[str] = None


class AgentTestHarness:
    DEFAULT_INPUTS = {
        "code": "def hello():\n    return 'world'\n",
        "text": "Sample text",
        "filename": "test_sample.py",
        "task": "Analyze",
        "target_dir": "nova",
        "issues": [],
        "previous_attempts": [],
        "error": "Sample error",
    }

    METHOD_PRIORITY = [
        "analyze", "review", "check", "scan_text", "scan",
        "design", "generate", "run", "cleanup", "status",
        "fix", "build",
    ]

    def __init__(self):
        self.results = []
        self.agents_dir = PROJECT_ROOT / "nova" / "agents"

    def _build_kwargs(self, method):
        sig = inspect.signature(method)
        kwargs = {}
        for name, param in sig.parameters.items():
            if name == "self" or param.default is not inspect.Parameter.empty:
                continue
            matched = None
            nl = name.lower()
            for k, v in self.DEFAULT_INPUTS.items():
                if k in nl or nl in k:
                    matched = v
                    break
            if matched is not None:
                kwargs[name] = matched
            elif "ctx" in nl or "context" in nl or "config" in nl:
                kwargs[name] = {}
            else:
                kwargs[name] = ""
        return kwargs

    def _pick_method(self, instance):
        for m in self.METHOD_PRIORITY:
            if hasattr(instance, m) and callable(getattr(instance, m)):
                return m
        return None

    def _find_instance(self, module, name):
        inst = getattr(module, name, None)
        if inst is not None and not inspect.isclass(inst) and not inspect.ismodule(inst):
            return inst
        for attr in dir(module):
            if attr.startswith("_"):
                continue
            obj = getattr(module, attr)
            if inspect.isclass(obj) or inspect.ismodule(obj) or callable(obj):
                continue
            if any(attr.endswith(s) for s in ("_agent", "Agent", "Analyzer", "Fixer", "Scanner", "Manager")):
                return obj
        return None

    async def test_agent(self, name):
        start = time.time()
        try:
            module = importlib.import_module(f"nova.agents.{name}")
        except Exception as e:
            return TestResult(name, "import", "FAIL", (time.time() - start) * 1000, error=f"ImportError: {str(e)[:50]}")
        instance = self._find_instance(module, name)
        if instance is None:
            return TestResult(name, "instance", "SKIP", (time.time() - start) * 1000, error="No instance")
        method_name = self._pick_method(instance)
        if method_name is None:
            return TestResult(name, "method", "SKIP", (time.time() - start) * 1000, error="No method")
        method = getattr(instance, method_name)
        kwargs = self._build_kwargs(method)
        try:
            if asyncio.iscoroutinefunction(method):
                result = await asyncio.wait_for(method(**kwargs), timeout=60.0)
            else:
                loop = asyncio.get_running_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: method(**kwargs)),
                    timeout=60.0,
                )
            return TestResult(name, method_name, "PASS", (time.time() - start) * 1000, output_type=type(result).__name__)
        except asyncio.TimeoutError:
            return TestResult(name, method_name, "TIMEOUT", (time.time() - start) * 1000, error=">10s")
        except Exception as e:
            return TestResult(name, method_name, "FAIL", (time.time() - start) * 1000, error=f"{type(e).__name__}: {str(e)[:50]}")

    async def run_all(self):
        all_files = sorted(self.agents_dir.glob("*.py"))
        targets = [
            f.stem for f in all_files
            if f.name != "__init__.py"
            and not f.name.startswith("_")
            and ".bak" not in f.name
        ]
        print("=" * 78)
        print(f"Agent Test Harness | {len(targets)} agents")
        print("=" * 78)
        for name in targets:
            r = await self.test_agent(name)
            self.results.append(r)
            icon = {"PASS": "[OK]", "FAIL": "[XX]", "SKIP": "[--]", "TIMEOUT": "[TT]"}[r.status]
            info = f"{r.duration_ms:7.1f}ms"
            if r.output_type:
                info += f" -> {r.output_type}"
            elif r.error:
                info += f" -> {r.error[:45]}"
            print(f"   {icon} {name:24s} [{r.method:12s}] {info}")
        self.print_summary()

    def print_summary(self):
        total = len(self.results)
        passed = sum(1 for r in self.results if r.status == "PASS")
        failed = sum(1 for r in self.results if r.status == "FAIL")
        skipped = sum(1 for r in self.results if r.status == "SKIP")
        timeouts = sum(1 for r in self.results if r.status == "TIMEOUT")
        print()
        print("=" * 78)
        print("SUMMARY")
        print("=" * 78)
        print(f"   Total:    {total}")
        if total > 0:
            print(f"   [OK] Pass:  {passed} ({passed / total * 100:.1f}%)")
        print(f"   [XX] Fail:  {failed}")
        print(f"   [TT] Time:  {timeouts}")
        print(f"   [--] Skip:  {skipped}")
        if failed or timeouts:
            print("\nFailures:")
            for r in self.results:
                if r.status in ("FAIL", "TIMEOUT"):
                    print(f"   * {r.name:24s} -> {r.error}")


async def main():
    h = AgentTestHarness()
    await h.run_all()


if __name__ == "__main__":
    asyncio.run(main())
