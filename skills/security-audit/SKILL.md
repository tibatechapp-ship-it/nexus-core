# Security Audit Skill

## الغرض
فحص أمني شامل للكود.

## الفحوصات الإلزامية
1. XSS (innerHTML, eval, document.write)
2. SQL Injection (string concatenation)
3. Path Traversal (../ في المسارات)
4. Command Injection (subprocess, os.system)
5. Secrets Leak (.env, tokens)
6. Insecure Transport (http://)

## التصنيف
- 🔴 حرج (يسمح بالتنفيذ عن بعد)
- 🟡 مهم (يكشف معلومات)
- 🟢 بسيط (ممارسات سيئة)
