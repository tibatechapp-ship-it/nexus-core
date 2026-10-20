# 📋 SCOPE.md — Nexus-Core Boundaries

**آخر تحديث:** 2026-10-20
**الإصدار الحالي:** v1.29.0
**HEAD:** طرف فرع `main` (بلا رقم ثابت — الرقم الثابت يتقادم؛ استخدم `git log -1 --oneline`)

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
>
> **استثناء مسجّل — 2026-10-19 (وضع الطيار الآلي):** tyba منح zyvo قيادة التطوير
> (وضع الطيار الآلي) — صلاحيات دائمة: كتابة/إصلاح الكود + تشغيل pytest بلا سؤال،
> والإيداع + **الدفع المباشر إلى `main`** على `origin` و`gitlab` ما دامت الاختبارات
> خضراء، وإنشاء فروع + دمجها، والوسوم + إصدارات GitHub عند إكمال مرحلة. القاعدتان
> 2/3 تبقيان الأصل العام، ويُسجّل هنا كل دفع مباشر إلى `main` (v1.18.1: 3 إيداعات
> صلة + إيداع الإصدار، الاختبارات 3111 ناجح @ 99.94%; v1.19.0: فرع
> `feature/exec-verify` + PR #23 مدموج (squash) ثم إيداع الإصدار على `main`،
> الاختبارات 3177 ناجح @ 99.94%; v1.20.0: 3 إيداعات صلة مباشرة على `main` +
> إيداع الإصدار (بذر العشرين + حفظ الجينوم)، الاختبارات 3201 ناجح @ 99.94%).

## 📊 الحالة

- الإصدار: v1.29.0
- الفرع: `main` (v1.29.0 مُصدَّر: حدود السجلات + حرس التسريب + مؤشرات الصحة)
- tracked: 1131 ملف
- modified: 0 (clean)
