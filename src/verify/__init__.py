"""التحقق بالتنفيذ — الطبقة التي تجعل ناتج الوكيل قابلاً للفحص بدل الثقة.

تصدّر المحرّك النقي والمُصلِح فقط. الـ``api`` **لا** يُستورَد هنا، فتبقى الحزمة
قابلة للاستيراد والاختبار بلا FastAPI (نفس نهج ``src.skills`` و``src.knowledge``).

معياري فقط (stdlib): ``tools/exec_sandbox`` يُستورَد **متأخّراً** وباسمه المجرّد،
وهو قابل للغياب بلا أن يكسر الاستيراد.
"""

from __future__ import annotations

from .engine import (
    MAX_ATTEMPTS,
    VerificationResult,
    compose_code,
    fix_loop,
    sandbox_available,
    sandbox_runner,
    verify_by_execution,
)
from .generators import build_fix_prompt, extract_code, llm_generate

__all__ = [
    "MAX_ATTEMPTS",
    "VerificationResult",
    "build_fix_prompt",
    "compose_code",
    "extract_code",
    "fix_loop",
    "llm_generate",
    "sandbox_available",
    "sandbox_runner",
    "verify_by_execution",
]
