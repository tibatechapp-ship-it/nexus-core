"""MIZAN — the security track (س1..س6, docs/MIZAN_ROADMAP.md).

Package layout:
    mizan.manifest    → requirements.txt parser with byte-exact round-trip
    mizan.advisories  → vulnerability advisory model (offline file + OSV.dev)
    mizan.fixer       → deterministic fix planner (minimal safe bumps)

The track closes the gap vs Snyk/Semgrep-class engines *within the repo's
governing constraint*: stdlib only, dry-run by default, honest degradation.
"""
from __future__ import annotations
