# Nexus Council — API

**العقد الرسمي**: `docs/openapi.yaml` (يُخدم حياً على `/api/openapi.yaml`).
**الواجهة التفاعلية**: `/docs/swagger` (أصول محلية في `docs/vendor/` — تعمل بلا إنترنت).

## نموذج الأخطاء (مهم)
`/api/craft` و `/api/build` يعيدان **HTTP 200 حتى عند الفشل الوظيفي** مع `ok=false`
(خطأ LLM، مسار غير آمن، فشل `py_compile`). افحص `ok` و `proof.ok` دائماً.
الرموز غير 200 للبروتوكول فقط: `401` عند تفعيل `CRAFT_AUTH_TOKEN` دون ترويسة صحيحة.

## Auth (اختياري)
```bash
export CRAFT_AUTH_TOKEN="secret"          # في .env
curl -X POST .../api/craft -H "X-Craft-Token: secret" -H "Content-Type: application/json" \
  -d '{"query":"..."}'
```
غير مضبوط = auth معطّل (الوضع المحلي الافتراضي — الخادم يستمع على 127.0.0.1 فقط).

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

## ملاحظة تشغيلية
أصول Swagger في `docs/vendor/` — إن غابت، نزّلها مرة:
```bash
curl -sL -o docs/vendor/swagger-ui.css       https://cdn.jsdelivr.net/npm/swagger-ui-dist@4/swagger-ui.css
curl -sL -o docs/vendor/swagger-ui-bundle.js https://cdn.jsdelivr.net/npm/swagger-ui-dist@4/swagger-ui-bundle.js
```
`main.py` يخدم كل شيء (لا سكربت خدمة منفصل).
