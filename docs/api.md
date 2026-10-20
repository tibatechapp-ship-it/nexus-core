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

## مسارات البوابة الموحّدة غير الموثّقة في `openapi.yaml` (مقصود)
`docs/openapi.yaml` يوثّق **واجهة منصة العمل** (`main.py`) وحدها، لأن حارس
الانحراف `test_spec_paths_match_app_both_ways` يقارن المواصفة بـ`main.app`
**في الاتجاهين**: أي مسار مذكور وغير منفَّذ في `main.py` = «مسار موهم» يُسقط CI.
لذلك مسارات البوابة (`nexus_agent.py` + `unified_agent.py`) الحيّة لكنها خارج
المواصفة **عن قصد** — توثيقها هنا بدلاً من `openapi.yaml`:

| المسار | الطريقة | الوصف |
|---|---|---|
| `/api/maintenance/metrics` | GET | صحّة الأسطول: `genome` (8 مفاتيح) + `by_priority{low,medium,high}` الحقيقي من سجلّ المهام + `by_priority_all_time` + `tasks{window_days,total_all_time,failure_pct,sample_sufficient}`. استعلام اختياري `window_days` (افتراضي 7). |
| `/api/maintenance/tasks` | GET | مهام صيانة مرشّحة (LOW/MED) من حالة الجينوم الحالية. استعلام اختياري `limit`. |

كلاهما **قراءة-فقط ولا يرمي أبداً**: فشل الجينوم أو السجلّ يُرجع أصفاراً صادقة
بدل خطأ. `sample_sufficient` = «هل بلغ حجم العيّنة حدّ الثقة» (طبقاً لـ
`NEXUS_MIN_SAMPLE`) — افحصه قبل بناء أي قرار على الأرقام.

## ملاحظة تشغيلية
أصول Swagger في `docs/vendor/` — إن غابت، نزّلها مرة:
```bash
curl -sL -o docs/vendor/swagger-ui.css       https://cdn.jsdelivr.net/npm/swagger-ui-dist@4/swagger-ui.css
curl -sL -o docs/vendor/swagger-ui-bundle.js https://cdn.jsdelivr.net/npm/swagger-ui-dist@4/swagger-ui-bundle.js
```
`main.py` يخدم كل شيء (لا سكربت خدمة منفصل).
