"""MIZAN — the security track (س1..س6, docs/MIZAN_ROADMAP.md).

Package layout:
    mizan.manifest      → requirements.txt parser with byte-exact round-trip
    mizan.advisories    → vulnerability advisory model (offline file + OSV.dev)
    mizan.fixer         → deterministic fix planner (minimal safe bumps)  [س1]
    mizan.reachability  → import-level tri-state reachability verdicts    [س2]
    mizan.taint         → bounded cross-file source→sink analysis         [س3]
    mizan.mirror        → local advisory mirror (sqlite3) with an SLA     [س4]
    mizan.grc           → static multi-repo GRC dashboard + control maps  [س5]
    mizan.rules         → custom-rules DSL (JSON over ast)                [س6]

The track closes the gap vs Snyk/Semgrep-class engines *within the repo's
governing constraint*: stdlib only, dry-run by default, honest degradation,
declared boundaries instead of pretended coverage.
"""
from __future__ import annotations
