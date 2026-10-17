---
title: nexus-core — ما هو المشروع
category: core
tags: nexus-core, overview, agents, architecture
pinned: true
---

# nexus-core

نظام وكلاء موحّد: **ذاكرة + تعلّم + أمن + وكلاء**، وهو دمج إطار عمل
`tyb-zyv-ai` (20 وكيلاً بمكتبة معيارية فقط) مع طبقة orchestration
`novamind-core`. الإصدار الحالي 1.14.0، الترخيص MIT، والمستودع
`github.com/tibatechapp-ship-it/nexus-core`.

## الطبقتان (مستودع واحد)
- **الإطار (framework, stdlib-only, يعمل على الهاتف):** `src/{agents,core,patterns,memory,learning,security,tools,tui}`
  + `zyvo-telegram.py` + `zyvo-voice.py`.
- **طبقة novamind (اختيارية):** `src/novamind/*` + `tests/novamind/*` + `scripts/novamind/`
  + سكربتات جذرية قديمة (يستوردها `src/novamind` — لا تُنقل ولا تُحذف).

## الأرقام الحقيقية (لا تُبالِغ)
- **20 وكيلاً مدمجاً** في الإطار (5 core / 5 planning / 5 quality / 5 ops).
- **~79 وحدة وكيل** في طبقة novamind.
- المعروض في `/api/status`: `agents {framework: 20, novamind: 79, total: 99}`.
- **30 أداة MCP** (20 `agent_*` + أمن + ملفات + git للقراءة فقط).
- المجلس (Council) = 6 أعضاء؛ الجينوم (genome_v2) مربوط بالمجلس.

## المعمارية (ملفات أساسية)
- `src/core`: types، `backend.py` (EchoBackend يعمل بلا شبكة)، model_router،
  context_manager، resilience، watchdog، streaming.
- `src/agents`: base، sub_agent (tools ⊆ parent)، registry، 20 وكيلاً؛ `all_agents(backend)`.
- `src/patterns`: supervisor / pipeline / fanout / delegation / blackboard / checkpoint.
- `src/memory`: 4 مخازن SQLite + manager (remember/recall/forget).
- `src/learning`: Experience → Lesson → Store → Injector + AntiForgetting.
- `src/security`: 8 وكلاء regex + orchestrator + CLI.
- `src/tools`: schemas + executor (أدوات قراءة فقط محصورة في الجذر) + run_with_tools.
- `src/novamind`: التفاصيل في `docs/novamind/ARCHITECTURE.md`.
