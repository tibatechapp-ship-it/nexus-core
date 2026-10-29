# Known Limitations — nexus-core

## TODO/FIXME Markers (22 total, all in novamind layer)

The following TODO markers exist in `src/novamind/`. They are documented here
rather than resolved because the novamind layer is sensitive and requires
architectural decisions before changes.

| File | Line | Marker | Category | Notes |
|------|------|--------|----------|-------|
| `src/novamind/agents/documentation_agent.py` | 84 | `TODO: add description` | Generated docstring placeholder | Auto-generated, not a real TODO |
| `src/novamind/core/automation/orchestrator.py` | 226 | `TODO: من Queue Manager` | Needs Queue Manager integration | Architectural decision needed |
| `src/novamind/core/company/anti_hallucination.py` | 52 | `# TODO: implement` | Test fixture string | Not a real TODO |
| `src/novamind/core/company/anti_hallucination.py` | 67 | `"TODO"` in must_not_contain | Code quality check | Intentional |
| `src/novamind/core/hive/factory/executor.py` | 236 | `TODO: اربط بـ core/llm_router` | Needs LLM router integration | Architectural decision needed |
| `src/novamind/factory/executor.py` | 235 | `TODO: اربط بـ core/llm_router` | Duplicate of above | Same as above |
| `src/novamind/factory/guards/output_guard.py` | 22 | `"TODO: implement"` | Test fixture string | Not a real TODO |
| `src/novamind/tools/isolated_agents_report.py` | 97, 122 | TODO detection code | Meta-tool | Not a real TODO |

### Not real TODOs (code quality tools)
- `src/novamind/core/analysis/error_detector.py:28` — regex pattern for detecting TODOs
- `src/novamind/core/safety/code_safety.py:141` — TODO detection
- `src/novamind/agents/multilang_analyzer.py:76,172` — TODO detection
- `src/novamind/core/hive/factory/executor.py:52` — instruction text (not code)
- `src/novamind/factory/executor.py:51` — instruction text (not code)

### Resolution plan
- Items needing architectural decision (orchestrator, executor) → defer to next sprint
- Auto-generated placeholders → acceptable, no action needed
- Test fixtures → intentional, no action needed
