# سياسة الأمان

## الإبلاغ عن ثغرة

لا تفتح Issue عاماً للثغرات الأمنية.

استخدم:

- GitHub Security Advisory:
  https://github.com/tibatechapp-ship-it/novamind-core/security/advisories/new
- أو البريد: security@[your-domain]

## التوقعات

- 48 ساعة: تأكيد الاستلام
- 7 أيام: تقييم مبدئي
- 30 يوماً: إصلاح + إصدار patch

## الممارسات الأمنية

### Secrets

- لا secrets في git
- استخدم .env (في .gitignore)
- GitHub Secrets للـ CI

### Dependencies

- dependabot يُحدّث أسبوعياً
- pip-audit في CI
- مراجعة دورية

### Code

- لا eval() أو exec() بلا مبرر
- تحقق من كل input
- لا except عارية
- Bandit في CI

### Logging

- log_redaction مُفعّل
- لا تسجيل secrets
- مستويات صحيحة

## الإصدارات المدعومة

- main: مدعوم
- آخر release: مدعوم
- أقدم: غير مدعوم
