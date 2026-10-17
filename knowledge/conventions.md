---
title: أعراف العمل والالتزامات
category: conventions
tags: git, commits, scope, branch, protected, conventions
pinned: true
---

# أعراف العمل

## الالتزامات (commits)
- تُقسَّم **حسب الاهتمام**: refactor نقي أولاً، ثم الميزة، ثم اختباراتها، ثم رفع الإصدار.
- صيغة conventional-commit إنجليزية: `feat(...)`, `fix(...)`, `test(...)`,
  `refactor(...)`, `docs(...)`, `chore(...)`.
- **البوّابات تُتحقق قبل كل التزام.**
- لا التزام بلا موافقة صريحة من صاحب المشروع.

## الفروع ونطاق العمل
- لا عمل مباشر على `main` — فرع ميزة (مثل `feature/novamind-factory`).
- رفع مزدوج: `origin` (GitHub) + `gitlab`.

## ملفات محميّة (لا تُلمس)
- `src/novamind/core/llm_router.py` — أي توصيل يجب أن يكون **opt-in** مع بقاء
  السلوك الافتراضي مطابقاً بايت-ببايت.
- منطق `src/council/engine.py` الافتراضي.
- مسار الأنماط الافتراضي في `src/patterns/`.

## أنماط تقنية ثابتة
- كل ملف يبدأ بـ `from __future__ import annotations`.
- `src/knowledge`, `src/skills` نمط: dataclass + `pathlib` + حقن الدلائل للاختبار.
- الأخبار/المفاتيح لا تُكتب في الملفات — تُقرأ من البيئة.
