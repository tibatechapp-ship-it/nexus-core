# 📋 SCOPE.md — Nexus-Core Boundaries

**آخر تحديث:** 2026-10-18
**الإصدار الحالي:** v1.15.0
**HEAD:** طرف الفرع `feature/novamind-factory` (بلا رقم ثابت — الرقم الثابت يتقادم؛ استخدم `git log -1 --oneline`)

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
- `src/novamind/genome/*` — genome v1
- `src/novamind/genome_v2.py` — genome v2 (نُفِّذ في v1.14.0)
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
2. اعمل على `feature/novamind-factory` فقط
3. لا تعديل مباشر على `feature/landing-page` أو `main`
4. commit بموافقة بشرية
5. لا تعمل في الخلفية — استئناف يدوي
6. SIGSTOP بعد كل مهمة

> **استثناء مسجّل — 2026-10-17:** tyba أعطى موافقة صريحة («الكل») على تنفيذ
> إصلاح F1–F5 وإيداعه على `feature/landing-page` ثم الوسم والدمج في `main`،
> لأن إصلاحات v1.13.4 تخصّ كودًا لا يوجد إلا على ذلك الفرع
> (`feature/novamind-factory` متأخر بإيداعين). القواعد 2/3 تبقى الأصل العام.
>
> **استثناء مسجّل — 2026-10-17 (v1.13.5):** tyba اختار «دمج + وسم إصدار» —
> فتح PR من `feature/landing-page` إلى `main` بعد إصلاح فشلات CI العشرين.
>
> **استثناء مسجّل — 2026-10-18 (v1.14.0):** tyba أعطى موافقة صريحة على بناء
> جينوم v2 وإيداعه: `src/novamind/genome_v2.py` (جديد) + ربط **غير مُقحِم** في
> `src/council/engine.py` (معامل اختياري، الناتج مطابق بايت-ببايت افتراضياً)
> + `tests/test_genome_v2.py`. عُومل الالتزام بقاعدة الفرع: العمل جرى على
> `feature/novamind-factory` بعد توحيده بـ`main` (fast-forward)، ثم PR إلى `main`.

## 📊 الحالة

- الإصدار: v1.15.0
- الفرع: feature/novamind-factory (أُعيد تسميته مرّتين في 2026-10-18: `feature/zyvo-workspace` → `feature/novamind-agent` → `feature/novamind-factory` — التسمية الأخيرة بموافقة tyba لمسارات التدريب/المهارات)
- tracked: 1040 ملف
- modified: 0 (clean)
