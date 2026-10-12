"""
CIDoctorAgent — وكيل طبيب CI
================================
يقرأ أخطاء CI من GitHub Actions ويسجلها ويقترح حلولاً.

الوظائف:
1. قراءة سجلات CI فاشلة
2. استخراج الخطأ الجذري (traceback, error type)
3. البحث في قاعدة أخطاء معروفة
4. اقتراح حل
5. إبلاغ الوكلاء المعنيين
"""
from __future__ import annotations

import json
import logging
import re
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger("nova.agents.ci_doctor")


# قاعدة أخطاء معروفة
KNOWN_ERRORS: Dict[str, Dict[str, str]] = {
    "PermissionError": {
        "pattern": r"Permission denied",
        "cause": "مسار محمي أو غير قابل للكتابة",
        "fix": "استخدم NOVAMIND_HOME أو /tmp بدلاً من /public",
        "agents": ["coder", "cleaner"],
    },
    "OperationalError": {
        "pattern": r"no such table: (\w+)",
        "cause": "جدول SQLite غير موجود",
        "fix": "أضف CREATE TABLE IF NOT EXISTS في _conn()",
        "agents": ["coder"],
    },
    "ModuleNotFoundError": {
        "pattern": r"No module named '(\w+)'",
        "cause": "حزمة مفقودة",
        "fix": "أضف الحزمة إلى requirements-ci.txt",
        "agents": ["coder", "analyzer"],
    },
    "F821": {
        "pattern": r"F821 undefined name",
        "cause": "اسم غير معرّف (flake8)",
        "fix": "أضف الاستيراد المناسب",
        "agents": ["coder", "lint_agent"],
    },
}


@dataclass
class CIError:
    """خطأ CI مستخرج"""
    job_name: str
    error_type: str
    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    cause: str = ""
    fix: str = ""
    agents: List[str] = field(default_factory=list)


class CIDoctorAgent:
    """وكيل طبيب CI"""

    def __init__(self):
        self.history: List[CIError] = []

    def analyze_log(self, log_text: str, job_name: str) -> List[CIError]:
        """يحلل سجل CI ويستخرج الأخطاء."""
        errors = []
        
        for err_type, info in KNOWN_ERRORS.items():
            matches = re.finditer(info["pattern"], log_text)
            for m in matches:
                err = CIError(
                    job_name=job_name,
                    error_type=err_type,
                    message=m.group(0),
                    cause=info["cause"],
                    fix=info["fix"],
                    agents=info["agents"],
                )
                # استخرج الملف والسطر إن أمكن
                line_match = re.search(
                    rf"([\w/\.\-]+\.py):(\d+)",
                    log_text[max(0, m.start()-200):m.start()+200]
                )
                if line_match:
                    err.file = line_match.group(1)
                    err.line = int(line_match.group(2))
                
                errors.append(err)
        
        self.history.extend(errors)
        return errors

    def report(self) -> str:
        """يولّد تقريراً."""
        if not self.history:
            return "✅ لا أخطاء CI"
        
        lines = ["🔴 أخطاء CI المكتشفة:", ""]
        for i, err in enumerate(self.history, 1):
            lines.append(f"{i}. [{err.job_name}] {err.error_type}")
            lines.append(f"   السبب: {err.cause}")
            lines.append(f"   الحل: {err.fix}")
            if err.file:
                lines.append(f"   الموقع: {err.file}:{err.line}")
            lines.append(f"   الوكلاء المسؤولون: {', '.join(err.agents)}")
            lines.append("")
        return "\n".join(lines)


def analyze_ci_logs(log_text: str, job_name: str = "unknown") -> str:
    """Wrapper."""
    agent = CIDoctorAgent()
    agent.analyze_log(log_text, job_name)
    return agent.report()
