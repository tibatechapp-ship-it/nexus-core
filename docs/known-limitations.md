# Known Limitations — nexus-core

> منذ **v1.49.1 (ب2.4)** هذه الوثيقة قابلة للتحقيق الآلي: اختبار
> `tests/test_known_limitations_truth.py` يمسح `src/novamind/` ويطابق كل
> سطر هنا حرفيًا — أي TODO جديد بلا إعلان يُفشل CI، وأي بند مُصلَح يجب
> حذفه من هذه الوثيقة في نفس الـPR.

## TODO/FIXME Markers — 19 total in `src/novamind/` — صفر معماري حقيقي

الربطان المعماريان الوحيدان (orchestrator→Queue Manager، executor→
core/llm_router) **نُفِّذا في v1.49.1** (ب2.2/ب2.3) — ما تبقى كلها ليست
دينًا معماريًا: كود كشف تكراري، fixtures، نصوص تعليمات، أو placeholder
مولّد، ولكل بند قرار معلن: **لا إجراء**.

| # | File | Line | Marker | Classification | Decision |
|---|------|------|--------|----------------|----------|
| 1 | `src/novamind/core/company/anti_hallucination.py` | 52 | `# TODO: implement` | Test fixture string | Intentional — لا إجراء |
| 2 | `src/novamind/core/company/anti_hallucination.py` | 67 | `"TODO"` in must_not_contain | Code quality check | Intentional — لا إجراء |
| 3 | `src/novamind/core/analysis/error_detector.py` | 28 | regex detects TODOs | Detection code (meta) | لا إجراء |
| 4 | `src/novamind/core/safety/code_safety.py` | 141 | TODO detection table | Detection code (meta) | لا إجراء |
| 5 | `src/novamind/core/safety/code_safety.py` | 142 | TODO detection table | Detection code (meta) | لا إجراء |
| 6 | `src/novamind/core/safety/code_safety.py` | 197 | `re.search(r"#\s*(TODO\|FIXME)")` | Detection code (meta) | لا إجراء |
| 7 | `src/novamind/agents/multilang_analyzer.py` | 76 | `# TODO/FIXME` comment label | Detection code (meta) | لا إجراء |
| 8 | `src/novamind/agents/multilang_analyzer.py` | 77 | TODO detection string | Detection code (meta) | لا إجراء |
| 9 | `src/novamind/agents/multilang_analyzer.py` | 81 | `"TODO/FIXME marker found"` | Detection code (meta) | لا إجراء |
| 10 | `src/novamind/agents/multilang_analyzer.py` | 172 | TODO detection string | Detection code (meta) | لا إجراء |
| 11 | `src/novamind/agents/multilang_analyzer.py` | 173 | TODO detection string | Detection code (meta) | لا إجراء |
| 12 | `src/novamind/agents/multilang_analyzer.py` | 177 | TODO detection string | Detection code (meta) | لا إجراء |
| 13 | `src/novamind/agents/quality_guardian.py` | 29 | `"no_todos": False  # TODO مسموح` | Detection code (meta) | لا إجراء |
| 14 | `src/novamind/tools/isolated_agents_report.py` | 97 | `"TODO" in line or ...` | Detection code (meta) | لا إجراء |
| 15 | `src/novamind/tools/isolated_agents_report.py` | 122 | TODO detection code | Detection code (meta) | لا إجراء |
| 16 | `src/novamind/agents/documentation_agent.py` | 84 | `TODO: add description` | Generated docstring placeholder | Auto-generated — لا إجراء |
| 17 | `src/novamind/factory/executor.py` | 52 | `- لا تستخدم placeholders (TODO…)` | Instruction text (not code) | لا إجراء |
| 18 | `src/novamind/core/hive/factory/executor.py` | 53 | Instruction text | Instruction text (not code) | لا إجراء |
| 19 | `src/novamind/factory/guards/output_guard.py` | 22 | `"TODO: implement"` | Test fixture string | Intentional — لا إجراء |

## Architectural links — resolved in v1.49.1

| Link | Resolution | Test |
|------|------------|------|
| orchestrator → Queue Manager (ب2.2) | `NovaMindOrchestrator(queue=TaskQueue())` — `_collect_metrics` يقرأ `queue.size()` فعليًا؛ والغياب صفر معلن لا تخمين | `tests/test_novamind_architecture_links.py` |
| executor → core/llm_router (ب2.3) | `pick_llm_for(specialty)` في النسختين (factory + hive/factory) يُعيد موجّه الإطار المركزي عبر `get_router()`؛ والفشل `None` معلن لا استثناء | نفس الملف |

## Not real TODOs — outside `src/novamind/`

- `tests/**` — fixtures مقصودة وتُدار بقواعد الاختبارات نفسها.
- `src/fleet/*`, `src/agents/*`, `src/coder/*` — خالية من TODO/FIXME
  (بوابة النظافة تتحقق من novamind هنا والبقية عبر ruff/مجلس الجودة).
