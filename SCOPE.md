# 📋 SCOPE.md — Nexus-Core Boundaries

**آخر تحديث:** 2026-10-17
**الإصدار الحالي:** v1.13.5
**HEAD:** طرف الفرع `feature/landing-page` (بلا رقم ثابت — الرقم الثابت يتقادم؛ استخدم `git log -1 --oneline`)

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

> **استثناء مسجّل — 2026-10-17:** tyba أعطى موافقة صريحة («الكل») على تنفيذ
> إصلاح F1–F5 وإيداعه على `feature/landing-page` ثم الوسم والدمج في `main`،
> لأن إصلاحات v1.13.4 تخصّ كودًا لا يوجد إلا على ذلك الفرع
> (`feature/zyvo-workspace` متأخر بإيداعين). القواعد 2/3 تبقى الأصل العام.
>
> **استثناء مسجّل — 2026-10-17 (v1.13.5):** tyba اختار «دمج + وسم إصدار» —
> فتح PR من `feature/landing-page` إلى `main` بعد إصلاح فشلات CI العشرين.

## 📊 الحالة

- الإصدار: v1.13.5
- الفرع: feature/landing-page
- tracked: 1029 ملف
- modified: 0 (clean)
