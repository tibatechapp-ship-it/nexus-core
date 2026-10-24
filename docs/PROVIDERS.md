 # Providers — دليل المزودين

## نظرة عامة

nexus-core يدعم 17 مفتاحًا من مزودَين مع Circuit Breaker.

| المزود | المفاتيح | الموديل | Base URL |
|--------|----------|---------|----------|
| Ollama Cloud | 7 | gemma4:31b-cloud | https://ollama.com/v1 |
| OpenRouter | 10 | nemotron-3.5-lightning:free | https://openrouter.ai/api/v1 |

## Ollama Cloud

- خطة Free
- موديل: gemma4:31b-cloud
- حصة أسبوعية
- زمن الرد: 2-3s

### الحصول على مفتاح
1. https://ollama.com/settings/keys
2. Create Key
3. انسخ المفتاح (hex، 57 حرفًا)

### التهيئة
OLLAMA_API_KEY_1=...
حتى OLLAMA_API_KEY_7

## OpenRouter

- خطة Free
- موديل: nvidia/nemotron-3.5-lightning:free
- 50 طلب/يوم لكل مفتاح
- زمن الرد: ~12s

### الحصول على مفتاح
1. https://openrouter.ai/keys
2. Create Key
3. انسخ المفتاح (sk-or-v1-، 73 حرفًا)

### التهيئة
OPENROUTER_API_KEY_1=sk-or-v1-...
حتى OPENROUTER_API_KEY_10

## Circuit Breaker

عند فشل مزود:

| Status | Cooldown |
|--------|----------|
| 401 (مفتاح ميت) | 24 ساعة |
| 404 (موديل متقاعد) | 24 ساعة |
| 429 (حصة يومية) | 24 ساعة |
| 429 (rate limit) | 60 ثانية |
| Timeout | 30 ثانية |

الملف: ~/.nexus-core/cooldowns.json

### إعادة ضبط
rm ~/.nexus-core/cooldowns.json
sv restart /data/data/com.termux/files/usr/var/service/nexus-core

## استكشاف الأخطاء

- all providers failed: احذف cooldowns.json وأعد التشغيل
- 401: مفتاح خاطئ
- 429: حصة منتهية
- 404: اسم موديل خاطئ

## روابط
- https://ollama.com/settings/keys
- https://openrouter.ai/keys
