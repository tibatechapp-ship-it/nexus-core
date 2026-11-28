# CLI Tools Reference

## 13 أداة

| الأداة | الغرض |
|--------|-------|
| nexus | CLI رئيسي (list/stats/run) |
| nexus-run | Smart Router |
| nexus-offline | Mock LLM |
| nexus-mock | Mock قديم |
| nexus-doctor | فحص شامل |
| nexus-metrics | إحصائيات LLM |
| nexus-cache | إدارة الكاش |
| nexus-rag | بحث دلالي |
| nexus-loop | حلقات ذاتية |
| nexus-web | Web Dashboard |
| nexus-council | مجلس (حرة) |
| nexus-council-topic | مجلس (24 موضوع) |

## أمثلة

### الوكلاء

    ./scripts/nexus list
    ./scripts/nexus stats
    ./scripts/nexus core
    ./scripts/nexus run coder "اكتب دالة"

### المجلس

    ./scripts/nexus-council-topic list
    ./scripts/nexus-council-topic run db_sqlite_vs_postgres
    ./scripts/nexus-council-topic history

### Router

    ./scripts/nexus-run "افحص أمنياً"

### الإحصائيات

    ./scripts/nexus-metrics today
    ./scripts/nexus-cache stats
    ./scripts/nexus-doctor

### Web

    ./scripts/nexus-web

### أوامر الوكلاء

    nexus ask "سؤال"
    nexus chat
    nexus delegate analyst "مهمة"

عند غياب مفاتيح Ollama تطبع هذه الأوامر سبباً واضحاً وتعيد رمز خروج `2`؛
`nexus status` يظل يعرض حالة Backend دون إيقاف باقي الفحص.

## المتغيرات البيئية

| المتغير | الغرض |
|---------|-------|
| NOVAMIND_HOME | مسار المشروع |
| WORKSPACE_DIR | مجلد العمل |
| NEXUS_STRATEGY | استراتيجية Router |
| NEXUS_AGENT | اسم الوكيل |
| NEXUS_PROMPT | الطلب |
| NEXUS_CMD | أمر CLI |
| NEXUS_ALLOW_MOCK_PROVIDER | تفعيل صريح لمزوّد المحاكاة فقط (`1`) عند غياب المزودين الحقيقيين |
