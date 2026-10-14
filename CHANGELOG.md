# Nexus-Core Changelog

## v1.0.0 — 2026-10-14

**First stable release.**

### Core
- 79 AI agents across 8 categories
- Hybrid Router (code / tool / decision)
- Council of 3 agents with real LLM streaming
- RAG with sqlite-vec (no numpy dependency)
- Loop Engine with self-learning
- Session cache (4572x speedup on repeats)
- Real-time monitoring (calls, tokens, cost)

### Council (Live)
- 3-member debate: Profiler / Analyst / Critic
- Real Arabic responses from Groq
- Explicit verdicts: [الحكم: X]
- Specific recommendations: [التوصية: Y]
- 2/3 majority consensus (1 round typical)
- 4-15s per full deliberation
- SSE streaming to browser

### Interfaces
- 13 CLI tools (nexus, nexus-hybrid, nexus-run, ...)
- Web Workbench (3-column + live theater)
- Python API
- REST endpoints (16)

### Testing & Quality
- 41 unit tests (pytest)
- 100% pass rate
- .gitignore covers generated files
- API keys never in git history

### Documentation
- README, ARCHITECTURE, USAGE, CLI
- Council live demo docs

## v0.23.x
- Streaming fixes, real verdicts, recommendation

## v0.22.0
- Live SSE streaming

## v0.9.0 – v0.21.0
- Incremental: registry, RAG, Council, Web, Router, 24 topics
