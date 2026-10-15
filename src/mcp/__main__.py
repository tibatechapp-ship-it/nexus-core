"""Run the nexus-core framework MCP server over stdio.

    python -m src.mcp

Exposes the 20 agents, the security scanner and the read-only workspace tools
(in the current directory) as MCP tools.
"""

from __future__ import annotations

import sys

from src.mcp.framework import serve_framework


def main(argv: list[str] | None = None) -> int:
    """Entry point: serve the framework surface over stdio."""
    args = sys.argv[1:] if argv is None else argv
    root = args[0] if args else None
    serve_framework(root=root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
