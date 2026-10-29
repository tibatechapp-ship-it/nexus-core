# Nexus Council — API

**العقد الرسمي**: `docs/openapi.yaml` (يُخدم حياً على `/api/openapi.yaml`).
**الواجهة التفاعلية**: `/docs/swagger` (أصول محلية في `docs/vendor/` — تعمل بلا إنترنت).

## نموذج الأخطاء (مهم)
`/api/craft` و `/api/build` يعيدان **HTTP 200 حتى عند الفشل الوظيفي** مع `ok=false`
(خطأ LLM، مسار غير آمن، فشل `py_compile`). افحص `ok` و `proof.ok` دائماً.
الرموز غير 200 للبروتوكول فقط: `401` (auth مفعّل والترويسة ناقصة/خطأ)، `429`
(تجاوز حدّ المعدّل)، `400` (JSON غير صالح)، `404` (معرّف/أصل غير موجود).

## Auth (اختياري)
```bash
export CRAFT_AUTH_TOKEN="secret"          # في .env
curl -X POST .../api/craft -H "X-Craft-Token: secret" -H "Content-Type: application/json" \
  -d '{"query":"..."}'
```
غير مضبوط = auth معطّل (الوضع المحلي الافتراضي — الخادم يستمع على 127.0.0.1 فقط).

## حارس الوصول في البوابة الموحّدة (v1.15.0)
`nexus_agent.py` يركّب طبقة أمنية **واحدة** (`src/security/access.py`) كـmiddleware
أمام كل المسارات — بلا لمس أي مسار، وتُضبط بمتغيّرات البيئة وحدها:

| المتغيّر | الافتراضي | الأثر |
|---|---|---|
| `NEXUS_AUTH_TOKEN` | فارغ (معطّل) | كل طلب **متغيّر** يجب أن يحمل `X-Auth-Token` |
| `NEXUS_RATE_LIMIT` | `120` | عدد الطلبات لكل `client+path` داخل النافذة (`0` ⇒ تعطيل) |
| `NEXUS_RATE_WINDOW` | `60` | طول النافذة بالثواني |
| `NEXUS_AUDIT_LOG` | معطّل | مسار ملف JSONL؛ `off`/`0` ⇒ معطّل |

الطرق المتغيّرة فقط محميّة (`POST`/`PUT`/`PATCH`/`DELETE`) — القراءات تمرّ دائماً.
`/api/status` يعرض حالة الحارس في المفتاح `guard` (لا يعرض التوكن أبداً).

```bash
# تفعيل التوكن + حدّ أضيق + سجل تدقيق
export NEXUS_AUTH_TOKEN="s3cret" NEXUS_RATE_LIMIT=30 NEXUS_AUDIT_LOG="$HOME/nexus-audit.jsonl"
curl -X POST http://127.0.0.1:8000/api/chat -H "X-Auth-Token: s3cret" \
  -H "Content-Type: application/json" -d '{"message":"مرحبا"}'
# 429 + Retry-After عند تجاوز الحد
```

## أمثلة
```bash
# بث SSE حي (fetch + ReadableStream؛ EventSource لا يدعم POST)
curl -N -X POST http://127.0.0.1:8000/api/deliberate -H "Content-Type: application/json" \
  -d '{"query":"هل نستخدم SQLite أم PostgreSQL؟"}'

# بحث في السجل
curl -s "http://127.0.0.1:8000/api/history?q=redis&limit=5"

# صياغة كود من وصف حرّ + مراجعة المجلس
curl -s -X POST http://127.0.0.1:8000/api/craft \
  -H "Content-Type: application/json" \
  -d '{"query":"fibonacci in python with a test","review":true}'
```

## سطح الـAPI: ثلاثة تطبيقات، عقد واحد
`docs/openapi.yaml` يوثّق **كل** مسار `/api/*` تخدمه التطبيقات الثلاثة — لا استثناء
مقصود ولا مسار «موثّق في مكان آخر»:

| التطبيق | دوره | مسارات | عمليات |
|---|---|---|---|
| `main.py` | منصة العمل: council + craft (وهو الذي يخدم المواصفة) | 12 | 12 |
| `unified_agent.py` | البوابة: workspace/chat/pipeline/training/knowledge/skills/verify/maintenance | 57 | 67 |
| `nexus_agent.py` | المشغّل: يعترض البوابة ويملك مسارات لا يملكها غيره (`/api/mcp/tools`، exec sandbox، تركيب vendor) | 34 | 36 |
| **الاتحاد** | مسارات فريدة عبر الثلاثة | **79** | **89** |

ثلاثة وعشرون مساراً مشتركة بين تطبيقين (مثل `/api/health`، `/api/build`،
`/api/council/*`) — المواصفة تذكرها مرة واحدة وتحمل `x-served-by` بأسماء
التطبيقات التي تخدمها، و`x-app` في كل عملية يحدّد **أي تطبيق** يملك شكل
الطلب/الاستجابة الموثّق. التطبيقات تستمع على منافذ مختلفة؛ اختر من تتصل به.

### حارس الانحراف
`tests/test_openapi.py` يحمّل التطبيقات الثلاثة فعلياً (مع `tools/` على المسار،
كما يفعل المشغّل) ويقارن اتجاهين:

* مسار حقيقي بلا توثيق ⇒ فشل.
* مسار موثّق بلا تنفيذ (phantom) ⇒ فشل.
* معاملات (path/query) أو جسم طلب في الكود وغير موثّق ⇒ فشل، وكذلك العكس؛
  الجسم الموثّق لمعالج يقرأ JSON خاماً يُعلَن صراحةً بـ`x-raw-body: true`.
* كل عملية متغيّرة يجب أن توثّق `401` و`429`، ولكل عملية `summary` و
  `operationId` فريد و`tag` معلَن، وكل `{param}` في المسار معلَن كـ`in: path`.
* كل `$ref` يُحلّ إلى مكوّن موجود، ولا مكوّن غير مستخدم.
* حجم السطح مثبَّت: لو اختفت عائلة مسارات لسبب استيراد صامت ⇒ فشل بدل سطح أصغر.

## دلالة `window_days` (نافذة زمنية صادقة)

`window_days` وكل النوافذ الزمنية (`by_risk_requests`، `tasks.window`) تُحتسب
فقط للسجلات التي تحمل حقل `ts` (أُضيف في **v1.31.2**، SCHEMA=2). سجلات ما قبل
v1.31.2 (SCHEMA=1) لا تحمل `ts` فتظهر في **`all_time` فقط**، لا في النافذة.

هذا **مقصود، لا باگ**: ختم السجلات التاريخية بزمن تقديري من `mtime` = اختلاق
بيانات في سجلّ قياس، وحذفها = إتلاف تاريخ تنفيذ حقيقي. الفجوة **مُعترَف بها
ومُوثَّقة، لا مُهاجَرة**.

أرقام مرجعية (مقياس 2026-10-20، `data/metrics.json`):
- إجمالي الصفوف: **162**
- تحمل `ts`: **2** (v1.31.2+)
- بلا `ts`: **160** (v1 legacy)

النتيجة العملية: بعد v1.31.2، `window_days` لا يكتمل إلّا بعد رصّ سجلات جديدة
تحمل `ts` — لا تعتمد على النافذة لقياس سلوك قديم.

## ملاحظة تشغيلية
أصول Swagger في `docs/vendor/` — إن غابت، نزّلها مرة:
```bash
curl -sL -o docs/vendor/swagger-ui.css       https://cdn.jsdelivr.net/npm/swagger-ui-dist@4/swagger-ui.css
curl -sL -o docs/vendor/swagger-ui-bundle.js https://cdn.jsdelivr.net/npm/swagger-ui-dist@4/swagger-ui-bundle.js
```
`main.py` يخدم كل شيء (لا سكربت خدمة منفصل).
