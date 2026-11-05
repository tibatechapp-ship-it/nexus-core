# لوحة ترتيب أسطول الوكلاء

**الإصدار:** `1.57.0` — **إجمالي الوكلاء:** 106

## الصحة العامة

| الحالة | العدد | النسبة |
|---|---:|---:|
| healthy | 105 | 99.1% |
| degraded | 0 | 0.0% |
| broken | 1 | 0.9% |

## التوزيع حسب الإطار

- **core**: 20
- **legacy**: 7
- **novamind**: 79

## توزيع الطبقات

- **S**: 77
- **A**: 2
- **B**: 19
- **C**: 8

## الترتيب (أعلى 25)

# | الوكيل | الإطار | الدرجة | الطبقة | الحالة | استيراد ms | استدعاء ms
---|---|---|---:|---|---|---:|---:
1 | a11y | novamind | 100.00 | S 🥇 | healthy | 0.0 | 0.49
2 | alert_bot | novamind | 100.00 | S 🥇 | healthy | 0.0 | 0.08
3 | analyst | core | 100.00 | S 🥇 | healthy | 0.0 | 0.02
4 | analyzer | novamind | 100.00 | S 🥇 | healthy | 0.0 | 0.19
5 | api_design | novamind | 100.00 | S 🥇 | healthy | 0.0 | 0.62
6 | arabic | novamind | 100.00 | S 🥇 | healthy | 0.0 | 0.0
7 | architect | core | 100.00 | S 🥇 | healthy | 0.0 | 0.01
8 | architecture | novamind | 100.00 | S 🥇 | healthy | 0.0 | 0.08
9 | auth | novamind | 100.00 | S 🥇 | healthy | 0.0 | 0.53
10 | builder | novamind | 100.00 | S 🥇 | healthy | 0.0 | 0.01
11 | chief_architect | novamind | 100.00 | S 🥇 | healthy | 0.0 | 0.0
12 | ci_doctor | novamind | 100.00 | S 🥇 | healthy | 0.0 | 0.12
13 | cicd | novamind | 100.00 | S 🥇 | healthy | 0.0 | 0.26
14 | code_review | novamind | 100.00 | S 🥇 | healthy | 0.0 | 0.91
15 | coder | novamind | 100.00 | S 🥇 | healthy | 0.0 | 0.69
16 | coder | core | 100.00 | S 🥇 | healthy | 0.0 | 0.01
17 | complexity | novamind | 100.00 | S 🥇 | healthy | 0.0 | 0.0
18 | compliance | novamind | 100.00 | S 🥇 | healthy | 0.0 | 0.31
19 | compliance | core | 100.00 | S 🥇 | healthy | 0.0 | 0.01
20 | crypto | novamind | 100.00 | S 🥇 | healthy | 0.0 | 0.47
21 | css | novamind | 100.00 | S 🥇 | healthy | 0.0 | 0.34
22 | data_scientist | novamind | 100.00 | S 🥇 | healthy | 0.0 | 0.0
23 | db_migration | novamind | 100.00 | S 🥇 | healthy | 0.0 | 0.25
24 | deadcode | novamind | 100.00 | S 🥇 | healthy | 0.0 | 0.0
25 | debugger | core | 100.00 | S 🥇 | healthy | 0.0 | 0.01

**قراءة الطبقات:** S ≥ 95، A ≥ 85، B ≥ 70، C ما دون.

**الدرجة =** صحة 30٪ + سرعة استيراد 15٪ + اكتمال دخول 15٪ + استدعاء 25٪ + SLO دور 15٪ (v1.49.0).

**ميزان الاستدعاء:** 100 استدعاء ناجح، 40 بناء فقط بلا عقد استدعاء، 0 فشل أو غير مُقاس — ومن لا يُقاس لا يُمنح نقاط استدعاء.

**القياس:** `mode: fake-clock` — بلا شبكة وبلا LLM حقيقي؛ ميزانيات SLO لكل دور في `src/fleet/benchmark.py` (`ROLE_SLO_BUDGETS`)، والتجاوز حتى 3× الميزانية يخفض المكوّن خطياً.

التقرير الآلي الكامل: `reports/fleet_inventory.json`.
