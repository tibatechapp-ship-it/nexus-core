#!/usr/bin/env python3
"""Demonstrate the agent tool library — offline, deterministic, exit 0.

Run it:  python3 scripts/demo_agent_tools.py

Lists every registered tool, then exercises the ones that need no network and
no LLM: ``get_current_time``, ``read_file`` (on this repo's README) and
``query_memory`` (an empty store is a valid, successful call).  The downloader
is shown through its SSRF guard — proof the security boundary is live without
touching the network.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# ``tools/`` holds the exec sandbox imported by its top-level name.
sys.path.insert(0, str(ROOT / "tools"))

from src.learning.tools import list_tools, safe_execute  # noqa: E402

DESCRIPTIONS = {
    "search_web": "Search the web (bounded, injectable fetcher).",
    "read_file": "Read a text file confined to the allowed roots.",
    "get_current_time": "Current time as ISO-8601 + unix seconds.",
    "query_memory": "Recall past interactions by keyword.",
    "execute_code": "Run code in the subprocess sandbox (strict timeout).",
    "consensus": "Several agents answer; one synthesizer merges them.",
    "download_file": "Download a file via aria2c (SSRF-protected, resumable).",
}


def _line(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    _line("Registered tools")
    tools = list_tools()
    for name in tools:
        state = "on" if tools[name].get("enabled") else "off"
        print(f"  - {name:<18} [{state}]  {DESCRIPTIONS.get(name, '')}")
    print(f"  ({len(tools)} tools)")

    _line("get_current_time")
    time_result = safe_execute("get_current_time")
    print(f"  ok={time_result.ok}  {time_result.value}")

    _line("read_file — README.md")
    readme = ROOT / "README.md"
    read_result = safe_execute(
        "read_file", path=str(readme),
        config={"tools": {"read_file": {"enabled": True,
                                        "allowed_roots": [str(ROOT)]}}},
    )
    if read_result.ok:
        first = read_result.value["content"].splitlines()[:3]
        print(f"  ok=True  bytes={read_result.value['bytes']}")
        for row in first:
            print(f"    | {row}")
    else:
        print(f"  ok=False  error={read_result.error}")

    _line("query_memory — empty store is still a success")
    mem_result = safe_execute("query_memory", keyword="demo")
    print(f"  ok={mem_result.ok}  rows={len(mem_result.value or [])}")

    _line("download_file — SSRF guard (no network)")
    dl_result = safe_execute("download_file", url="http://127.0.0.1/x")
    print(f"  ok={dl_result.ok}  error={dl_result.error}")

    _line("Done")
    print("All demonstrated tools are wired and safe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
