# Nexus-Core — دليل تدريب الوكلاء (AGENT_TRAINING)

هذا المستند هو **الحقيقة التشغيلية** لطبقة التدريب: كيف يكتسب الوكيل هويّته ومهاراته
ومعرفته، كيف يُدرَّب ويُقيَّم وتُمنح له الشهادة، وكيف تعود نتيجة التدريب درساً يُغيّر
سلوك النظام لاحقاً. النصّ يعكس ما هو **منفَّذ فعلاً** في الشجرة، ويشير صريحاً إلى ما
لم يُوصَل بعد.

> المصدر التخطيطي: `docs/AGENT_TRAINING_PLAN.md`. هذا الملف = الجانب التنفيذي منه.

---

## الطبقات الأربع (من الهوية إلى السلوك)

| # | الطبقة | الملف | الدور |
|---|---|---|---|
| 1 | **الأرشيف/الهوية** | `src/agents/manifest.py` | مصدر واحد لهوية الوكيل: اسمه، مجموعته، أدواته، مهاراته، بواباته |
| 2 | **المعرفة المشتركة** | `src/knowledge/` | معرفة المشروع التي تُحقن في التعليمات قبل كل مهمّة |
| 3 | **المهارات** | `src/skills/` | إجراءات مُثبَتة (`SKILL.md`) تُحقن حسب مهارات الوكيل من الأرشيف |
| 4 | **التدريب والميدان** | `src/novamind/training/` | منحنى تدريب → تقييم حتمي → شهادة → درس → جينوم |

الترتيب مهمّ: الطبقة 1 تُغذّي 2 و3 و4 (الأرشيف يقرّر من يملك أي مهارة)، والطبقة 4
هي الوحيدة التي **تكتب** نتائج دائمة.

---

## 1) الأرشيف — `src/agents/manifest.py`

`AgentManifest` كائن `frozen` يُسقَط (projection) من فئة الوكيل نفسها + جدول `_EXTRAS`:

- **المفردات المُتحقَّقة** (أي اسم خارجها ⇒ `ManifestError`):
  `KNOWN_TOOLS` (22) · `KNOWN_SKILLS` (5) · `KNOWN_GATES` (6: ruff/mypy/annotations/
  pytest/adversarial/smoke) · `KNOWN_ADVERSARIAL` (14 متجهاً).
- الدوال: `build_manifests()` / `all_manifests()` / `get_manifest(name)` /
  `manifest_problems()` / `validate_suite()`.
- `memory_scope` لكل وكيل (نطاق ذاكرته)، و`tools_requires_write` مشتقّ من أدواته.

الأرشيف **لا يغيّر أي سلوك وقت التشغيل** — هو مرجع للقراءة فقط.

---

## الطبقة 2 — المعرفة المشتركة

* `src/knowledge/base.py` — `KnowledgeBase` تقرأ markdown مع front-matter من
  مجلّدَي البذرة والمستخدم:
  * البذرة: `<repo>/knowledge/` (`nexus-core.md`, `gates.md`, `conventions.md`،
    والأخيران + الأول **مُثبَّتان** `pinned`) + `training-model.md`.
  * تجاوز المستخدم: `~/.config/nexus/knowledge/` — يفوز عند تشابه الاسم.
  * الترتيب في `select()`: وثائق جامعة ← مثبَّتة أخرى → وثيقة الفئة → الأكثر صلة
    (تشابه مرجّح: العنوان+الوسوم ×2، المتن ×1) مع تطبيع عربي (أ/إ/آ→ا، ى→ي، ة→ه،
    وحذف التشكيل) وتوقّف عربي/إنجليزي.
* `src/knowledge/inject.py` — `inject_into_prompt(agent, task, ...)`: يبني
  `[تعليمات الوكيل | النص المخصّص] + [كتلة المعرفة] + [قسم المهمّة]`.
  `include_task=False` يُبقي المهمّة للاختيار فقط (دردشة: الرسالة هي دور المستخدم).
* `src/knowledge/api.py` — `GET /api/knowledge` و `GET /api/knowledge/{name}`.

**الوصلة**: `nexus_agent.py::_agent_system(agent_id, task)` يبني تعليمات الوكيل من
نصّه + كتلة المعرفة + كتلة المهارات، وكل طبقة داخل `try/except` مستقل — فشل طبقة
يُرجع التعليمات الخام ولا يكسر الدردشة أبداً. `src/council/builder.py` يحقن نفس
الكتلة في تعليمات المُخطِّط (blueprint).

---

## الطبقة 3 — المهارات

* الدلاء: `<repo>/skills/<name>/SKILL.md` (بذرة المستودع: `code-review`,
  `security-audit`, `architecture-review`, `documentation`, `testing`) ثم
  `~/.config/nexus/skills/<name>/SKILL.md` — **ملف المستخدم يفوز** عند تطابق الاسم.
* `src/skills/inject.py` — `agent_skill_names(agent)` يقرأ المهارات **من الأرشيف**
  (الطبقة 1 تبقى المصدر الواحد)، و`inject_skills_into_prompt()` تُلحق كتلة
  `### المهارات المُفعَّلة (Skills)` بحدّ أقصى 3 مهارات افتراضياً.
* `src/skills/api.py` — `GET /api/skills` و `GET /api/skills/{name}`.

---

## الطبقة 4 — محرّك التدريب

### نموذج القرار (`models.py`)
* `GRADUATION_MIN_SCORE = 0.75` · `RETRAIN_FLOOR = 0.5`
* `verdict_for(graduated, score, completion_rate, critical)` — **الدليل يسبق الرقم**:
  فشل حرج أو إتمام < 50% ⇒ `failed`؛ وإلّا ما دون الأرضية ⇒ `needs_retraining`.
  الأرضية تُرفع بالسقف فقط: `min_score = max(min_score, 0.75)`.

### المخزن (`store.py`)
SQLite (WAL، اتصال لكل عملية، `SCHEMA_VERSION=1`) بجدولَي `training_runs` و
`training_certificates` + فهارس. مسار القاعدة: `$NEXUS_TRAINING_DB` →
`$NEXUS_DB` (مجلد `training.db` نفسه) → `<repo>/data` → مجلد مؤقت.

### المحرّك (`engine.py`)
* **المُقيّم الحتمي افتراضياً**: `deterministic_evaluator` يحسب الدرجة من
  `sha256(salt|agent|skill|index)` موزّعة ±0.12 حول جودة المدرّب ⇒ **قابل للتكرار**
  (المسار القديم في `novamind/core/training/` يستخدم `random.gauss` فلا يصلح
  للمقارنة بين تشغيلين).
* **المنحنى** = وحدات خطة التدريب الحقيقية (`training_plans`) **+** وسوم مهارات
  الأرشيف (تطبيع `code-review` → `code_review`) ⇒ الأرشيف يبقى مصدر الهوية.
* **التخرّج** = إتمام ≥ 0.8 ودرجة موزونة ≥ 0.75 ولا وحدة تحت 0.5.
* **الشهادة** تُصدر فقط عند التخرّج ودرجة ≥ 0.75. توقيع Ed25519 **اختياري**:
  يُفحص وجود `cryptography.hazmat...ed25519` أولاً، وإن غاب ⇒ **توقيع فارغ، ولا
  يُلفَّق أبداً** (واقع Termux).

---

## حلقة الميدان (`field.py`) — العائد من التدريب

التدريب لا يُسجَّل فقط؛ كل تشغيل يُغذّي النظام:

1. **`absorb(run)`** ⇒ درس واحد في `learning.Lesson` (مخزن **لكل وكيل**؛ الدمج
   العابر للوكلاء ينسب درس وكيل إلى آخر).
2. **`observe(run)`** ⇒ الجينوم: تقييم **دقّة التقييم الذاتي** (ما ادّعاه الوكيل
   مقابل الحقيقة).
3. **`evolve()`** ⇒ قرار لكل وكيل من `genome_v2.advise`
   (`observe`/`promote`/`keep`/`retrain`/`revise`)، و**`retrain` وحده يُعدِّل**
   (`genome.mutate`) — والتعديل يُصفّر المشاهدات فيعمل كتهدئة تمنع الارتجاج.
4. **`tick(run)`** = الثلاثة معاً + تقرير `{lesson, genome, evolved, mutated}`.

المتغيّرات: `NEXUS_TRAINING_FIELD` (`0`/`off`/`no`/`false` ⇒ تعطيل) و
`NEXUS_TRAINING_LESSONS_DB` (افتراضياً `lessons.db` بجانب قاعدة التدريب).

## الجينوم — قناتان مستقلّتان على الصفّ نفسه (`src/novamind/genome_v2.py`)
* **قناة الحكم** (council): موقف العضو مقابل الحكم النهائي، مع انكماش الثقة
  `n/(n+K)` وEWMA للتحديث.
* **قناة النتيجة** (مهامّ): `observe_outcome(agent_id, ok, duration, quality, task)`
  — `ok` هي الحقيقة، والفشل دائماً عيّنة 0.0 مهما كانت الجودة.
  `blend_fitness` يدمج القناتين بثقة كل منهما، وصفّ بلا نتائج مهامّ يحتفظ بالمعادلة
  القديمة حرفياً.

> **غير موصول بعد**: لا مسار إنتاجي يستدعي `observe_outcome` (حلقة الميدان تُغذّي
> قناة الحكم فقط). وصله بتشغيل الوكلاء الحقيقي = v1.16.0.

---

## واجهة HTTP

| المسار | الوصف |
|---|---|
| `GET /api/training/status` | حالة النظام + إحصاءات الميدان |
| `GET /api/training/agents` | الوكلاء الذين دُرِّبوا |
| `GET /api/training/plan/{agent_id}` | منحنى الوكيل ووحداته |
| `POST /api/training/run` | تشغيل تدريب واحد `{agent_id, quality, min_score?}` |
| `POST /api/training/batch` | تدريب مجموعة |
| `GET /api/training/runs` · `/runs/{run_id}` | السجلّ |
| `GET /api/training/certificates` | الشهادات الصادرة |
| `GET /api/training/field` | إحصاءات حلقة الميدان |
| `GET /api/training/lessons?agent_id=&limit=` | الدروس المستخرجة |
| `GET /api/training/fitness?limit=` | لياقات الوكلاء (الجينوم) |
| `POST /api/training/evolve` | تشغيل خطوة تطوّر يدوية |
| `GET /api/knowledge` · `/knowledge/{name}` | المعرفة المشتركة |
| `GET /api/skills` · `/skills/{name}` | المهارات |

**التركيب**: تُسجَّل كل مجموعة عبر `register(app, ...)` الذي يستدعي
`app.router.routes.extend(...)` مباشرة — لأن `include_router` في FastAPI الحديثة
**مؤجَّل** (يضيف عنصراً نائباً `_IncludedRouter`) ولا يُفكّ أبداً داخل تطبيق مثبَّت
بـ`mount`، فيظهر 404 من البوابة بينما يعمل في الاختبار المباشر. اختبار الانحدار
يجب أن يمرّ عبر `mount` لا عبر التطبيق العاري.

## لوحة الأكاديمية (Agent Academy)
`web/unified_ui.html`: زرّ **Agent Academy** ⇒ نافذة بثلاث تبويبات — **مراحل**
(المنحنى)، **دروس** (المستخرجة)، **لياقات** (الجينوم) — مع زرّي تحديث وإعادة تدريب
ودعم عربي/إنجليزي. تعمل عبر `/api/training/*`.

> **تنبيه**: هذه الواجهة يخدمها `unified_agent.py` على `/` — وفي البوابة الموحّدة
> يفوز الأب (`main.py`) بـ`/` ويعرض `index.html`. لمعاينتها شغّل
> `NOVAMIND_PORT=8010 python3 unified_agent.py` وحده.

## البوابات (لا يعتبر العمل منتهياً قبلها)
```bash
ruff check .
mypy zyvo-telegram.py zyvo-voice.py src
python scripts/check_annotations.py
python -m pytest --cov --cov-fail-under=95 --ignore=tests/novamind
```
`src/novamind/*` خارج بوابات الإطار (له بوابته الخاصة بملف تغطية مخصّص، مثل
`coverage-genome.ini`). تحذير: `scripts/dev_check.sh` لا يقيس التغطية إطلاقاً —
لا تنقل رقماً منه.

## ما لم يُنفَّذ بعد
1. وصل `observe_outcome` بتشغيل الوكلاء الحقيقي (v1.16.0).
2. توسيع الأرشيف من 20 وكيلاً إلى الـ79 في طبقة novamind (لا سجلّ موحّد لها اليوم؛
   العدد المعلن «79» هو **عدّ ملفات** `src/novamind/agents/*.py` لا سجلّ وكلاء).
