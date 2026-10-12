# ADR-001: Vertical Slice First

## الحالة

مقبول

## السياق

النظام يتكون من طبقات أفقية (memory, tools, orchestration, product). خطر: بناء الطبقات معزولة دون
تكامل.

## القرار

نبني شريحة عمودية كاملة قبل التوسع الأفقي: CLI → review → findings → store → metrics → audit

## النتائج

- ✅ إثبات التكامل مبكرًا
- ✅ نقاط فشل واضحة
- ❌ بطء التوسع الأولي
