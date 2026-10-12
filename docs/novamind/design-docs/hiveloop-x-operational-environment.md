# HiveLoop-X Operational Environment

## المكونات

- `hive/vertical_cli.py` — CLI العمودي
- `hive/core/store.py` — طبقة DB
- `hive/audit/hive_audit.py` — التدقيق
- `hive/self/*` — التعلّم الذاتي
- `hive/eval/*` — قياس الجودة

## تدفق البيانات

review → classify → findings → store → audit → metrics
