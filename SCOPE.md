# 📋 SCOPE.md — Nexus-Core Boundaries

**آخر تحديث:** 2026-10-16
**الإصدار الحالي:** v1.13.1.1
**HEAD:** 4914131

---

## 🔴 محمي تماماً (لا تعديل مباشر)

- `nexus_agent.py` — الخادم الموحد
- `main.py` — workbench
- `pyproject.toml` — الإصدار
- `src/council/*.py` — قلب Council
- `src/novamind/error_memory.py` — السلك الأول
- `src/novamind/core/llm_router.py` — LLMRouter (موصول بـ error_memory)
- `.env` — أسرار

## 🟡 حذر (بموافقة صريحة)

- `src/novamind/council/*` — Council الداخلي
- `src/novamind/genome/*` — genome (v1.14.0 قريباً)
- `src/council/gatekeeper.py` — ethics_gate (v1.14.1)

## 🟢 مسموح (إضافات فقط)

- `tests/test_*.py` (جديد)
- `tests/novamind/test_*.py` (جديد)
- `docs/*.md`
- `reports/*.md`
- `CHANGELOG.md`
- `SCOPE.md`

## 🚫 محظور دائماً

- `src/council/isolation.py`
- `history.db`
- `zyvo.bin`
- `/tmp/*` (استخدم `~/`)

## 🎯 قواعد zyvo

1. اقرأ قبل أن تكتب
2. اعمل على `feature/zyvo-workspace` فقط
3. لا تعديل مباشر على `feature/landing-page` أو `main`
4. commit بموافقة بشرية
5. لا تعمل في الخلفية — استئناف يدوي
6. SIGSTOP بعد كل مهمة

## 📊 الحالة

- الإصدار: v1.13.1.1
- الفرع: feature/landing-page
- tracked: 1029 ملف
- modified: 0 (clean)
