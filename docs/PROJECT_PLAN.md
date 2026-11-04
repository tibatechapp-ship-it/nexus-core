# Project Plan: NovaMind Landing Page

> ملاحظة (v1.52.0): الصفحة الهبوطية صارت **HTML ثابتاً** (`index.html` +
> `index.ar.html` + `index.en.html` + `i18n.js`) بعد أن كانت مشروع Astro —
> لا حزمة ولا بناء، فقط ملفات تُقدَّم كما هي. البنود أدناه محدّثة لتطابق
> الواقع، ومرحلة النشر مُغلقة بالكامل.

## Phase 1: Initialization
- [x] Static landing page (no build step — plain HTML/CSS/JS)
- [x] Bilingual pages (`index.ar.html` · `index.en.html`) with `i18n.js` switcher
- [x] Global styles (dark theme #0d1117, responsive)

## Phase 2: Components
- [x] Redirector `index.html` → language page (script + `<noscript>` fallback)
- [x] Hero, stats, features, tech-stack sections
- [x] Footer with repository links

## Phase 3: Assembly
- [x] RTL layout for the Arabic page (`dir="rtl"`)
- [x] Responsive breakpoints
- [x] Hover animations

## Phase 4: Deploy
- [x] Deploy workflow `.github/workflows/deploy-landing.yml`
      (static upload to GitHub Pages on every push touching `landing/**`,
      plus `workflow_dispatch`) — مراجعة بوابة
      `tests/test_workflow_health.py` تثبت أن الفلتر `push.branches`
      سليم ويستهدف main
- [x] Enable GitHub Pages (Pages environment wired in the workflow:
      `permissions: pages: write, id-token: write` + `actions/deploy-pages`)
- [x] Landing content merged to main
- [x] Workflow-health gate: `tests/test_workflow_health.py` — كل ملف
      workflow يُفحص بنيوياً (parse + name + triggers + فلاتر نظيفة +
      jobs بخطوات)، ويثبت عقد «الدفع إلى main يُطلق CI/النشر»

## Phase 5: PWA for the product shell (v1.52.0)
- [x] `manifest.webmanifest` (عربي أولاً · RTL · ألوان المنصة الحقيقية)
- [x] `sw.js`: غلاف أوفلاين cache-first مع نسخة مخبأ، و`/api/` يمرّ
      دائماً للشبكة (حالة الطلب لا تُخبّأ أبداً)، وتدهور أوفلاين صادق 503
- [x] أيقونات 192/512 PNG بقناع maskable آمن (زوايا معتمة #0d1117)
- [x] ربط كامل في `index.html` (manifest + theme-color + apple-touch-icon
      + تسجيل SW محروس بالبروتوكول)
- [x] عقد آلي: `tests/test_pwa_assets.py` (manifest صادق الأبعاد، أيقونات
      موجودة فعلية بحجمها المعلن، SW لا يلمس API، الربط موجود)
