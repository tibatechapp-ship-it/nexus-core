# العقود المستقرة — Stable Interfaces Contract

> **الوعد**: الواجهات المذكورة هنا **مستقرة** — أي تغيير في توقيع أو سلوك
> موثَّق أدناه يُفشل CI عبر اختبار العقد (`tests/test_llm_router_contract.py`)
> و(`tests/test_observability_otrace.py`) ويستوجب مراجعة معلنة وتحديث هذه
> الوثيقة في PR نفسه. هذا هو سدّ ض7 (اختبار عقد المزوّد) —
> docs/V2_ROADMAP.md م3.

---

## 1. عقد `llm_router` — `novamind.core.llm_router` (ض7)

الواجهة العامة للتعامل مع مزوّدي LLM. كل وحدات المنصة (المجلس،
الوكلاء، verify، learning) تستدعي عبر هذه الأسماك فقط.

### 1.1 الدوال العامة — التوقيعات المثبتة

| الرمز | التوقيع المثبَّت |
| --- | --- |
| `LLMRouter.generate` | `(self, prompt, system='', role='fast', temperature=0.2, max_tokens=None, provider=None, allow_fallback=True)` |
| `LLMRouter.generate_for_task` | `(self, task_type: str, prompt: str, system: str = '', temperature: float = 0.2, max_tokens=None) -> Dict` |
| `LLMRouter.async_generate` | `(self, prompt: str, system: str = '', role: str = 'fast', temperature: float = 0.2, max_tokens: int = 2000) -> Dict` |
| `LLMRouter.async_generate_for_task` | `(self, task_type: str, prompt: str, system: str = '', temperature: float = 0.2, max_tokens: int = 2000) -> Dict` |
| `LLMRouter.async_generate_batch` | `(self, requests: List[Dict]) -> List[Dict]` |
| `LLMRouter.list_providers` | `(self)` → قائمة قواميس `name/priority/enabled/calls/failures/models/last_error` |
| `LLMRouter.stats` | `(self)` → `{total_providers, total_calls, total_failures, providers}` |
| `MockProvider.generate` | `(self, prompt, system='', **kwargs)` → قاموس بدون شبكة |
| `get_router` | `() -> LLMRouter` (singleton — يُعاد إنشاؤه إن كان mock-فقط) |

### 1.2 عقد نتيجة `generate`

قاموس واحد دائمًا (لا استثناءات للفشل الشبكي):

* نجاح: `{"ok": True, "text": str, "provider": str, "model": str, "elapsed": float}`
* فشل: `{"ok": False, "text": "", "provider": "", "model": "", "error": str, "elapsed": float}`
* المفتاح `ok` هو الحكم الوحيد — المتصل يفحصه ولا يفترض حقولًا أخرى.

### 1.3 عقد قاطع الدارة (Circuit Breaker v1.46.0+)

الثوابت المثبتة: `_COOLDOWN_DAILY=86400` · `_COOLDOWN_HOURLY=3600` ·
`_COOLDOWN_MINUTE=60` · `_COOLDOWN_BRIEF=30`.

| الحالة | المدة | السبب |
| --- | --- | --- |
| 401 / `invalid_api_key` | 86400 | `invalid_key` |
| 404 / `not found` / `no longer available` | 86400 | `model_retired` |
| 429 + كلمات يومية (`daily`, `rpd`, `quota`, `billing`…) | 86400 | `daily_quota` |
| 429 + ترويسة `retry-after` / `x-ratelimit-reset-*` | `max(60, الثواني المحلَّلة)` | `rate_limit_reset` |
| 429 عادي | 60 | `rate_limit` |
| 5xx | 120 | `server_error` |
| نص يحوي `timeout`/`timed out`/`connection` | 30 | `network` |
| غير معروف | 60 | `unknown` |

سلوك مثبَّت إضافي:

* `_cooldown_provider(name, seconds)` يضع الاسم في `self._cooldowns`
  حتى `time.time() + seconds`؛ `_is_cooled_down(name)` ترجع False
  أثناء التبريد وTrue بعده.
* `_parse_duration`: `"120"→120` · `"90s"→90` · `"5m"→300` · `"2h"→7200` ·
  `""/غير مطابق→None`.
* `_key_hash(key)`: أول 12 hex من SHA-256 — يُستخدم لملف التبريد
  المُدار بحيث يُلغى التبريد تلقائيًا عند تبديل المفتاح.
* `_extract_status(exc)`: `status_code` ثم `response.status_code` ثم
  أول 4xx/5xx في نص الاستثناء.
* تبريد مزوّد يُستثنى من `_get_ordered_candidates` حتى انتهاء مدته.

---

## 2. عقد التتبّع العميق — `src.observability.otrace` (م3)

### 2.1 مخطط سطر span — `nexus.trace/v1`

الحقول الإلزامية (الترتيب لا يهم؛ الوجود إلزامي):

| الحقل | النوع | الدلالة |
| --- | --- | --- |
| `schema` | str | ثابت `"nexus.trace/v1"` |
| `ts` | ISO-8601 UTC | لحظة الاكتمال |
| `start_ts` | ISO-8601 UTC | لحظة البدء (ترتيب replay) |
| `trace_id` | 32 hex | معرّف الجلسة (نمط OTel) |
| `span_id` | 16 hex | معرّف الخطوة |
| `parent_span_id` | 16 hex أو `""` | الأب في الشجرة |
| `seq` | int | ترتيب البدء داخل الجلسة |
| `name` | str | اسم الخطوة |
| `agent` | str | المنفّذ |
| `duration_ms` | float ≥ 0 | المدة |
| `outcome` | `"ok"/"error"` | الحصيلة |
| `attributes` | قاموس scalars | وصف آمن بلا محتوى مستخدم |

### 2.2 الضمانات

* **الخصوصية افتراضية**: لا إرسال خارجي إلا بضبط `NEXUS_OTLP_ENDPOINT`
  صراحةً؛ المُصدِّر `OTLPExporter` عبر urllib فقط وفشله بلا أثر.
* **مرشّح الخصوصية**: مفاتيح السمات `prompt/content/messages/text/input/
  output/question/answer/response/body/transcript` تُسقَط دفاعيًا عند
  الإنشاء **وعند الكتابة** معًا؛ القيم غير-scalar تُسقَط.
* **best-effort**: فشل القرص أو الشبكة لا يُسقط العمل المُتتبَّع أبدًا.
* **الدوران**: تجاوز `MAX_BYTES` (5MB) يدوّر إلى `.1` والقديم يُضغط
  zlib إلى `.1.z`؛ `read_spans`/`replay_steps` تقرأ الثلاثة (`.1.z`,
  `.1`, الحي) بترتيب `seq`.
* **الاستئناف البصري**: `replay_steps(path)` خطوات بترتيب البدء —
  واجهة PWA: `GET /api/traces/sessions` و`GET /api/traces/{session_id}`
  (session_id = 32 hex صارم).

---

## 3. إجراء تعديل عقد

1. افتح PR يعدّل الواجهة **وهذه الوثيقة واختبار العقد معًا**.
2. اذكر السبب في الوصف (نمو المواصفة، إصلاح أمني، …).
3. مرّة واحدة كل إصدار رئيسي (v2.0.0) تُراجع العقود كاملة وتُعلن
   الإهمالات بإطار زمني لإزالتها (دورة إصدار واحد على الأقل).
