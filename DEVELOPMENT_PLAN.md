# DEVELOPMENT_PLAN.md

## الحالة
17 مفتاح (7 Ollama + 10 OpenRouter)، Circuit Breaker، 3s استجابة.

## محظور
1. لا تعدّل llm_router.py دون فهم Circuit Breaker
2. لا تحذف cooldowns.json أثناء التشغيل
3. لا تلمس .env أو *.secret
4. لا force push / reset --hard
5. لا تعدّل docs/legacy/ أو scripts/chess/

## المرحلة 1: E2E (يوم 1)
tests/test_e2e_chat.py بـ httpx
- test_chat_arabic_response
- test_chat_streaming_events
- test_auth_required
- test_provider_fallback
pytest -v → 4 passed

## المرحلة 2: تفكيك unified_ui.html
1616 → 300 HTML + CSS + JS

## المرحلة 3: توثيق
README + ARCHITECTURE + PROVIDERS

## المرحلة 4: print→logger
src/ فقط، 900 موضع

## المرحلة 5: تفكيك unified_bot.py
1913 → 200 سطر

## الأولويات
1. E2E (2h) ⭐
2. UI split (4h)
3. Docs (2h)
4. logger (4h)
5. Bot split (8h)
