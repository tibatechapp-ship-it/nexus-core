# خطة تدريب الوكلاء + الواجهة

> خطة بأسلوب **البوّابات فقط** (Goal / Tasks / Criteria / Dependencies / Gate) — بلا أيّ تقديرات زمنية.
> النموذج المرجعي = **النموذج الذي تعمل به zyvo نفسها** (الهوية → الذاكرة → المهارات → البوابات → العدائية → الحلقة الذاتية).

---

## 0. الحقيقة في سطر واحد

كل ما يلزم للتدريب **موجود في الكود بالفعل** — لكنه **غير موصول**:
لا واحد من `training` / `learning` / `skills` / `certification` معروض في الـ API أو الواجهة.
الاتصال الوحيد الحيّ حالياً = `genome_v2` ← المجلس. الباقي جزر معزولة.

---

## 1. النموذج المرجعي — كيف "تُدرَّب" zyvo (6 طبقات)

هذا هو النموذج الذي طلبت محاكاته. كل وكيل في nexus-core يجب أن يمتلك نفس الطبقات:

| # | الطبقة | المعنى عند zyvo | الخليّة المقابلة في nexus-core |
|---|--------|------------------|--------------------------------|
| 1 | **الهوية** Identity | system-prompt: من أنا، نبرتي، لغتي، خطوط الرفض | `BaseAgent.system_prompt` + persona في genome — **جزئي، بلا مرجع موحّد** |
| 2 | **الذاكرة الساخنة** Hot memory | AGENTS.md يُحمَّل تلقائياً كل جلسة | `src/memory/` (4 مخازن + RAG + traces) — **موجود، غير محقون لكل مهمة** |
| 3 | **المهارات أولاً** Skills-first | امسح قائمة المهارات، حمّل SKILL.md المطابق **قبل** التنفيذ | `src/skills/loader.py` (5 مهارات افتراضية) — **موجود، غير موصول بأي وكيل** |
| 4 | **البوّابات** Gates | لا "تمّ" بلا تشغيل أمر التحقق الحقيقي | `quality_gate.py` + `real_evaluator.py` + `graduation_min_score` — **موجود داخل حزمة التدريب فقط** |
| 5 | **العدائية والحدود** | قائمة مسموح/مرفوض + متجهات هجوم يجب أن تصمد | `tests/adversarial/` (92) + `src/security/` (8 وكلاء) + `hallucination_guard` — **موجود** |
| 6 | **الحلقة الذاتية** Self-improvement | تجربة → درس → مهارة؛ أصلح الخطأ وسجّله | `src/learning/` (Experience→Lesson→Store→Injector→Orchestrator، AntiForgetting) + `genome_v2` — **موجود، موصول جزئياً** |

**الخلاصة:** الفجوة ليست "نقص بنية" — بل **الوصل**: هوية موحّدة (طبقة 1) تَشُدّ الطبقات 2–6 إلى مهمة واحدة.

---

## 2. الجرد الحقيقي (ما يوجد فعلاً — تحقّق 2026-10-18)

### 2.1 وكلاء
- **الإطار**: `src/agents/` = 20 وكيلاً مدمجاً (analyst, architect, coder, reviewer,
  tester, debugger, planner, …) + `base.py`/`sub_agent.py`/`registry.py`/`state.py`/`metrics.py`.
- **novamind**: `src/novamind/agents/` (~79 وحدة) — الطبقة العسكرية/التسلسل الهرمي.
- الإجمالي المعروض في `/api/status` = **99** (20 + 79).

### 2.2 مصنع التدريب — `src/novamind/core/training/` (12 ملف، **غير معروض**)
- `training_plans.py` — `TrainingPhase` (foundation→specialization→simulation→evaluation→teamwork→field→advanced→retraining)، `TrainingModule` (name, phase, hours, description, prerequisites, test_cases, min_score)، `TrainingPlan` (agent_spec, modules, graduation_test, **graduation_min_score=0.75**) + `UNIVERSAL_MODULES` + خطط لكل تخصص.
- `training_executor.py` — `enroll(agent_id, spec)` → `TraineeProgress`، `run_full_training`.
- `training_simulator.py` — سيناريوهات + تنقيط.
- `training_orchestrator.py` — `train_agent`, `retrain_weak_agent`, `batch_train`.
- `trainer.py` + `TrainerPool` · `retrainer.py` (طابور إعادة تدريب) · `quality_gate.py` (verdict: passed/needs_retraining/failed) · `real_evaluator.py` (تقييم بـ LLM حقيقي) · `agent_adapters.py` + `agent_real_runner.py` · `factory.py`.
- `dual_realm.py` — عزل `Realm.TRAINING` عن `Realm.OPERATIONS`.

### 2.3 التعلّم — `src/learning/` (يوثّق في `docs/LEARNING.md`)
`Experience` → `ExperienceCollector` → `LessonExtractor` (LLM) → `LessonStore` (Jaccard dedup) → `LessonInjector` → `LearningOrchestrator` + `ContinualLearningManager` (جدولة) + `AntiForgetting` (حماية/تعارض/دمج).

### 2.4 المهارات — `src/skills/loader.py`
`SKILL.md` في `~/.config/nexus/skills/<name>/` · 5 مهارات افتراضية مبذورة (code-review, security-audit, architecture-review, documentation, testing) · `list_skills/load/search`. **لا وكيل يقرأها.**

### 2.5 الشهادات — `src/certification/` : `manager.py` + `signer.py` (توقيع إن توفّر `cryptography`، وإلا SHA256).

### 2.6 الجينوم
- v1 `src/novamind/genome/scoring.py`: `success_rate`, `avg_latency`, `consensus_avg`, `speed_score`, `compute_standing`, `classify` → promoted(≥0.7)/active/probation(<0.4).
- v2 `src/novamind/genome_v2.py`: دقة الحكم (stance مقابل verdict)، انكماش الثقة `n/(n+K)`، EWMA α=0.35، سمات لكل موقف، elite(≥0.75)/stable/probationary(<0.35)، `MIN_OBSERVATIONS=5`.
- **موصول بالمجلس فقط** — الوكلاء الـ20 بلا سجل مكانة.

### 2.7 الواجهة
| الملف | الحجم | الدور | ما يخصّ التدريب |
|------|------|------|------------------|
| `index.html` | 759 سطر | كونسول الورشة (مجلس ⚖️، جينوم 🧬، craft، build، review، صوت) | لا شيء |
| `web/unified_ui.html` | 1324 سطر | دردشة المحرّك (محادثات، traces، منتقي وكلاء، نافذة مجلس، لوحة جينوم) | زر `♻ إعادة تدريب` = تصفير إحصاءات **فقط** |
| `dashboard_view.html` | 135 سطر | لوحة عرض | لا شيء |

### 2.8 الفجوات (مرتبة بالأثر)
| # | الفجوة | الأثر |
|---|--------|------|
| G1 | لا `/api/training/*` إطلاقاً | مصنع التدريب كامل لكن لا يمكن تشغيله من الواجهة |
| G2 | `src/skills` غير موصول بأي وكيل | المهارات المكتوبة ميتة |
| G3 | لا حقن تلقائي للذاكرة/الدروس في مسار المهمة | الوكيل "ينسى" بين التشغيلات |
| G4 | `certification` غير موصول بـ graduation | لا شهادة تُصدر فعلياً |
| G5 | الجينوم يغطي المجلس فقط | الـ20 بلا مكانة/انضباط |
| G5 | لا "مرجع وكيل" موحّد | الهوية/المهارات/البوّابات مبثوثة بلا مصدر واحد |
| G6 | لا لوحة أكاديمية في الواجهة | المستخدم لا يرى أي من هذا |

---

## 3. النموذج المقترح — `AgentManifest` = المرجع الواحد

ملف واحد يصف كل وكيل (الطبقة 1 من نموذج zyvo)، ويصبح المصدر الوحيد للهوية والتدريب والواجهة:

```python
@dataclass(frozen=True)
class AgentManifest:
    id: str                  # "coder"
    title: str               # "المهندس المبرمج"
    spec: str                # مفتاح خطة التدريب (training_plans)
    identity: str            # system-prompt: الدور، النبرة، اللغة، خطوط الرفض
    skills: list[str]        # ["code-review", "testing"] ← تُحقن قبل التنفيذ
    tools: list[str]         # أدوات مسموحة (⊆ سجل الأدوات)
    gates: list[str]         # أوامر/شروط التحقق قبل "تمّ"
    adversarial: list[str]   # متجهات يجب أن تصمد
    memory_scope: str        # نطاق الذاكرة/الدروس
    tools_required: bool     # هل يحتاج ReAct loop
```
**المبدأ:** الـ manifest هو المرجع الواحد؛ مصنع التدريب القديم (novamind) يصبح **محرّكاً خلفه** لا بديلاً عنه.

---

## 3.5 مراحل التدريب (التسلسل الرسمي الموجود في `TrainingPhase`)
```
FOUNDATION → SPECIALIZATION → SIMULATION → EVALUATION → TEAMWORK → FIELD → ADVANCED
                                                                        ↘ RETRAINING (عند الهبوط)
```
البوّابة في كل مرحلة = `min_score` (افتراضي 0.7)؛ التخرّج = `graduation_test` بـ `graduation_min_score ≥ 0.75`.

---

## 4. المراحل (Gates only — بلا تقديرات زمنية)

### P0 — الجرد والتثبيت
- **Goal:** مرجع واحد محقّق لكل ما يوجد/موصول/معروض.
- **Tasks:** جدول الجرد (§2) كملف `docs/AGENT_TRAINING_INVENTORY.md`؛ تأكيد غياب `/api/training`؛ تسجيل خط أساس للبوّابات.
- **Criteria:** الملف مُلتزَم؛ خط الأساس مسجّل رقمياً.
- **Dependencies:** لا شيء.
- **Gate:** `scripts/dev_check.sh` أخضر كما هو (بلا تغيير سلوك) + مراجعة tyba للجدول.

### P1 — Agent Manifest (الهوية الموحّدة)
- **Goal:** manifest واحد لكل وكيل = المصدر الواحد.
- **Tasks:** `src/agents/manifest.py` (dataclass + محمّل + تحقّق)؛ ملف manifest لكل وكيل من الـ20؛ تحقّق أن `tools ⊆ ` سجل الأدوات و`skills` موجودة.
- **Criteria:** 20/20 manifest صالح؛ manifest مشوّه يُفشل الاختبار.
- **Dependencies:** P0.
- **Gate:** `tests/test_agent_manifest.py` أخضر + ruff/mypy/annotations نظيفة + البوّابة الكاملة بلا انخفاض تغطية.

### P2 — توصيل المهارات (Skills-first)
- **Goal:** الوكيل يحمّل مهاراته **قبل** التنفيذ.
- **Tasks:** طبقة حقن في `BaseAgent`/`run_with_tools`: تُقرأ `manifest.skills` → يُحقن محتوى `SKILL.md` في الرسائل (+ أثر في `traces`)؛ دليل مهارات في المستودع (`skills/`) كبذرة + تجاوز المستخدم في `~/.config/nexus/skills`؛ `GET /api/skills` + `GET /api/skills/{name}`.
- **Criteria:** مهمة مراجعة كود تُحقن لها مهارة `code-review` (اختبار يثبته + أثر حيّ في `traces`).
- **Dependencies:** P1.
- **Gate:** اختبارات المهارات + تشغيل حيّ واحد يُظهر المهارة في `traces`.

### P3 — أنبوب التدريب (Theory → Simulation → Graduation)
- **Goal:** `train_agent(id, spec)` يُنتج شهادة حقيقية.
- **Tasks:** وصل `training_plans` → `TrainingExecutor` → `TrainingSimulator` → `RealEvaluator` → `QualityGate` → `certification`؛ جداول تقدّم في `sessions.db`؛ `POST /api/training/enroll`, `GET /api/training/{id}`, `POST /api/training/{id}/run` (SSE للتقدّم)، `GET /api/graduates`.
- **Criteria:** شهادة **فقط** عند `score ≥ graduation_min_score`؛ فشل ⇒ `needs_retraining` بلا شهادة (اختبار سالب صريح).
- **Dependencies:** P2.
- **Gate:** اختبارات التدريب خضراء + تخرّج حقيقي واحد بـ LLM حقيقي.

### P4 — الحلقة الميدانية (تعلّم + جينوم)
- **Goal:** كل تشغيل حقيقي يُغذّي التعلّم والجينوم تلقائياً.
- **Tasks:** خطّاف في مسار (chat / council / agent-run) → `ExperienceCollector.record`؛ تشغيل `LearningOrchestrator` عبر `ContinualLearningManager` مع `AntiForgetting`؛ تغذية نتيجة الوكلاء الـ20 إلى `genome_v2` أيضاً؛ هبوط لمستوى probation ⇒ أمر `Retrainer`؛ `GET /api/learning/{lessons,stats}`.
- **Criteria:** قابل للقياس — بعد N تشغيل: عدد الدروس > 0، المكانات تحرّكت، عضو تحت العتبة ولّد أمر إعادة تدريب (سكربت عرض يُثبت الثلاثة).
- **Dependencies:** P3.
- **Gate:** مخرجات سكربت العرض + الاختبارات.

### P4.5 — تحديث الجينوم v3 (الوكلاء الـ20)
- **Goal:** مكانة لكل وكيل لا للمجلس فقط.
- **Tasks:** توسيع `genome_v2` ليقبل مصدر نتائج ثانياً (مهمة→نجاح/فشل + زمن + جودة البوّابة)، بلا كسر مسار المجلس (back-compat: بلا مصدر ثانٍ ⇒ سلوك مطابق بايت-ببايت).
- **Criteria:** اختبارات v1/v2 قائمة كما هي + اختبارات المصدر الثاني.
- **Gate:** `tests/test_genome_v2.py` + الجديدة خضراء، تغطية `src/council` و`genome_v2` = 100%.

### P4.5 تصميم الواجهة — «الأكاديمية 🎓»
- **Goal:** كل ما سبق مرئي وقابل للتشغيل من الواجهة.
- **الشاشات:**
  1. **Roster** — 99 وكيلاً: شريط مكانة/لياقة، وسم حالة (elite/stable/probationary)، شارة شهادة.
  2. **بطاقة الوكيل** — الهوية (قابلة للتحرير)، المهارات، البوّابات، الشهادة، الخطّ الزمني (أحداث genome)، آخر الدروس المستفادة.
  3. **مشغّل التدريب** — اختر وكيلاً + تخصصاً → تقدّم المراحل مباشرةً (SSE)، سجل حيّ، نتائج الاختبارات، النتيجة، ثم الشهادة.
  4. **متصفّح المهارات/الدروس** — ماذا تعلّم كل وكيل، أي مهارات يملك.
  5. **ربط المجلس** — بعد verdict: حركة المكانة المرئية + «ما تعلّمه هذا العضو».
- **عقد API جديد:** `GET /api/agents` (مُوسَّع: skills/standing/certificate) · `/api/training/*` · `/api/skills` · `/api/learning/*` · `GET /api/academy/status`.
- **Criteria:** تصيير headless بـ chromium بلا أخطاء كونسول؛ **كل** مسار جديد موثّق في `docs/openapi.yaml` وحارس الانحراف (`tests/test_openapi.py`) يمرّ في الاتجاهين.
- **Dependencies:** P2 + P3 + P4.5 (genome).
- **Gate:** `make check` أخضر + تحقّق headless (لقطة + DOM).

### P5 — التقسية والإصدار
- **Goal:** شحن.
- **Tasks:** توثيق `docs/AGENT_TRAINING.md`؛ مصادقة على المسارات المُعدِّلة (`TRAINING_AUTH_TOKEN` بنمط `CRAFT_AUTH_TOKEN` — معطّلة عند غياب المتغيّر)؛ حدّ معدّل؛ سجل تدقيق؛ رفع الإصدار (4 ملفات: pyproject/CHANGELOG/openapi/SCOPE).
- **Criteria:** كل البوّابات خضراء، CI أخضر، لا سرّ مُلتزَم، لا مسار مُعدِّل بلا حماية.
- **Gate:** PR مدمج + وسم + Release.

---

## 5. مخطط الواجهة (تخطيطي)

```
┌─ nexus-core · الأكاديمية 🎓 ────────────────────────────────────┐
│ [المجلس ⚖️] [الجينوم 🧬] [الأكاديمية 🎓] [المهارات 🎯] [الدروس 📚] │
├──────────────────────────┬──────────────────────────────────────┤
│  الوكلاء (99)            │  بطاقة الوكيل: coder                  │
│  ● coder      ▲ 0.82     │  الهوية     : [قابل للتحرير…]         │
│  ● reviewer   ▲ 0.74     │  المهارات   : code-review · testing   │
│  ⚠ debugger   ▼ 0.38     │  البوّابات  : ruff · mypy · pytest    │
│  ○ planner    ─ 0.50     │  الشهادة    : ✅ v1.14.0 (0.88)       │
│  …                       │  الخط الزمني: …                        │
│                          │  [🎓 درِّب الآن]  [♻ إعادة تدريب]     │
├──────────────────────────┴──────────────────────────────────────┤
│  مشغّل التدريب — debugger · spec=debugging                       │
│  foundation ✓ → specialization ✓ → simulation ▶ (3/7)            │
│  …سجل حيّ من SSE…                                                │
└──────────────────────────────────────────────────────────────────┘
```

---

## 6. قرارات مفتوحة (مع توصيتي)

| # | القرار | التوصية |
|---|--------|---------|
| D1 | أين تعيش المهارات؟ | بذرة في المستودع `skills/` + تجاوز المستخدم `~/.config/nexus/skills` (يعمل للفريق والمستخدم) |
| D2 | كلفة التدريب: LLM حقيقي أم محاكاة؟ | **هجين**: المحاكاة للحارس والاختبارات (offline، حتمية)، والتقييم الحقيقي للتخرّج فقط |
| D3 | النطاق: 20 أم 99؟ | ابدأ بالـ20 (سطح البوّابة)، ثم وسّع لاحقاً |
| D4 | الشهادة: موقّعة أم JSON؟ | موقّعة عند توفّر `cryptography`، وإلا SHA256 (يحاكي `signer` الحالي) |
| D5 | مصنع التدريب novamind: يُعرَض كما هو أم يُعاد تطبيعه؟ | تطبيع: الـ manifest هو المرجع، والمصنع يصبح محرّكاً خلفه |

---

## 7. المخاطر

- **ازدواج الحقيقة:** وجود نظامي تدريب (manifest الجديد + مصنع novamind) — يعالجه D5.
- **كلفة LLM:** تقييم حقيقي لكل وكيل = بطيء/مكلف — يعالجه D2 (محاكاة افتراضية).
- **انحدار التغطية:** `src/council` و`genome_v2` مقيسان بتغطية؛ أي سطر جديد يحتاج اختباراً.
- **جوائز الواجهة:** `index.html` هشّ (3 كتل سكربت مُلتفّة) — أي إضافة = كتلة جديدة تلفّ لا تُعدِّل (النمط المستخدم في v1.11/v1.12).

## 8. ما لا نلمسه (محمي)
`src/novamind/core/llm_router.py` · منطق `src/council/engine.py` الافتراضي · مسار الأنماط الافتراضي في `src/patterns/` — أي توصيل يكون **opt-in** مع بقاء السلوك الافتراضي مطابقاً بايت-ببايت.

## 9. بوّابات التحقق (الأوامر الحقيقية)
```bash
scripts/dev_check.sh                                   # 4 بوّابات (بلا تغطية)
python -m pytest --cov --cov-fail-under=95 --ignore=tests/novamind   # البوّابة الحقيقية
ruff check . && mypy zyvo-telegram.py zyvo-voice.py src && python scripts/check_annotations.py
```
