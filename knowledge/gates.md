---
title: بوّابات التحقق — الأوامر الحقيقية
category: gates
tags: gates, verify, ruff, mypy, pytest, coverage
pinned: true
---

# بوّابات التحقق

لا يُقال "تمّ" بلا تشغيل الأمر الحقيقي. هذه هي البوّابات الفعلية للمستودع:

```bash
ruff check .
mypy zyvo-telegram.py zyvo-voice.py src
python scripts/check_annotations.py        # كل دالة يجب أن تكون مُعلّمة بأنواع
python -m pytest --cov --cov-fail-under=95 --ignore=tests/novamind   # البوّابة الحقيقية
make check                                 # lint + type + annotations + cov في أمر واحد
```

## نطاق البوّابات (اتّساق إلزامي)
- **مقيس:** سطح الإطار `src/{agents,core,patterns,memory,learning,security,tools,tui}`
  + سكربتات zyvo + الأجزاء الجديدة مثل `src/knowledge`, `src/council`.
- **مستبعد (له اختباراته الخاصة):** `src/novamind`, `tests/novamind`,
  `scripts/novamind`, وسكربتات novamind القديمة في الجذر.

## أرقام مرجعية
- الإطار: `pytest --cov --cov-fail-under=95 --ignore=tests/novamind`.
- العتبة في `pyproject.toml [tool.coverage.report] fail_under`.
- **تحذير:** `scripts/dev_check.sh` يشغّل pytest **بلا** `--cov` — لا تقتبس منه
  نسبة تغطية أبداً.

## درس
عند فشل معيار مورد/أداء: **قِس الأرضية أولاً** قبل تعديل الكود — غالباً المعيار
خاطئ النطاق، والإصلاح الأمين = تصحيح المعيار بدليل + اختبار حارس.
