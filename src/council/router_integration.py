"""Router Integration — متى نحوّل للمجلس؟"""
import re

COUNCIL_SIGNALS = [
    r"أم",                              # أي "أم"
    r"أيهما",
    r"أي.*أفضل",
    r"أي.*نختار",
    r"\bcompare\b|\bcomparison\b",
    r"قارن|مقارنة|الفرق بين",            # ← جديد
    r"\bvs\.?\b",
    r"\bwhich\b.*\bbetter\b",
    r"\bdecision\b|\bdecide\b",
    r"\bor\b.*[?؟]",
]

HIGH_RISK = [
    # ⚠️ لا نستخدم \b مع العربية — لأن \b يعتمد على ASCII
    r"production",
    r"security",
    r"ثغرة|ثغرات",
    r"أمني|أمنية|أمنياً|آمن",
    r"اختراق|هجوم",
    r"\bauth\b",
    r"password",
    r"مصادقة|كلمة السر",
    r"\bdeploy\b|\bdeployment\b",
    r"نشر",
]


def should_use_council(question):
    q = question.lower()
    for p in HIGH_RISK:
        if re.search(p, q, re.IGNORECASE):
            return True
    for p in COUNCIL_SIGNALS:
        if re.search(p, q, re.IGNORECASE):
            return True
    return False


def get_council_reason(question):
    q = question.lower()
    for p in HIGH_RISK:
        if re.search(p, q, re.IGNORECASE):
            return "risk-high"
    for p in COUNCIL_SIGNALS:
        if re.search(p, q, re.IGNORECASE):
            return "decision-signal"
    return "no-council"
