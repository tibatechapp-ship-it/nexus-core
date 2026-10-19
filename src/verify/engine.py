"""التحقق بالتنفيذ (execution-based verification).

الفكرة كلّها في سطر: لا نصدّق أنّ الوكيل «أجاب» — بل نُشغّل ناتجه فعلاً
ونقرأ ``exit_code``. رمز الخروج هو الحكم؛ الـLLM **مستشار** يُصلح الكود فقط.

كل شيء قابل للحقن: ``runner`` (مُشغّل الكود) و``generate`` (مُصلِح الكود)
يُمرَّران كوسائط، فالاختبارات تعمل بلا تنفيذ حقيقي وبلا شبكة. المُشغّل
الافتراضي يلفّ ``exec_sandbox`` — **نفس** الصندوق الرملي الذي يخدم
``/api/exec`` في البوابة، فلا نسخة ثانية من منطق التنفيذ.

معياري فقط (stdlib) باستثناء الاستيراد المتأخّر لصندوق التنفيذ.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

__all__ = [
    "MAX_ATTEMPTS",
    "VerificationResult",
    "compose_code",
    "fix_loop",
    "sandbox_available",
    "sandbox_runner",
    "verify_by_execution",
]

PYTHON = "python"

#: سقف محاولات الإصلاح — تنفيذات فعلية، لا نداءات LLM.
MAX_ATTEMPTS = 6

#: توقيع المُشغّل: ``(code, language, stdin, timeout) -> dict``.
Runner = Callable[[str, str, str, int], dict]

#: توقيع المُصلِح: ``(task, code, result, system) -> كود جديد``.
Fixer = Callable[..., str]

_PY_ALIASES = frozenset({"python", "py"})


@dataclass(frozen=True)
class VerificationResult:
    """حكم واحد على قطعة كود — بعدد التنفيذات وسبب صريح."""

    passed: bool
    reason: str
    code: str
    language: str
    attempts: int
    detail: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """تمثيل JSON-آمن (البوابة تُعيده كما هو)."""
        return {
            "passed": self.passed,
            "reason": self.reason,
            "code": self.code,
            "language": self.language,
            "attempts": self.attempts,
            "detail": list(self.detail),
        }


def compose_code(code: str, tests: str = "", language: str = PYTHON) -> str:
    """يُلحق كتلة الاختبارات بالكود (بايثون فقط).

    لغات أخرى + اختبارات ⇒ ``ValueError`` صريح — لا نتجاهل اختباراً بصمت
    فنُعلن نجاحاً لم يُقس.
    """
    body = code.rstrip("\n")
    probe = tests.strip()
    if not probe:
        return body
    if language.lower().strip() not in _PY_ALIASES:
        raise ValueError("الاختبارات مدعومة في بايثون فقط")
    return f"{body}\n\n{probe}"


def sandbox_available() -> bool:
    """هل صندوق التنفيذ قابل للاستيراد الآن؟ (بلا استيراد فعلي ثقيل)."""
    try:
        import exec_sandbox  # noqa: F401  (frozen probe — لا نُبقيه)
    except Exception:
        return False
    return True


def sandbox_runner(
    code: str, language: str = PYTHON, stdin: str = "", timeout: int = 10
) -> dict:
    """يشغّل الكود في ``exec_sandbox`` ويعيد قاموسه كما هو.

    يرفع استثناءً فقط حين يكون الصندوق نفسه غير متاح أو اللغة غير مدعومة —
    و``verify_by_execution`` يحوّل ذلك إلى فشل مفهوم (``runner-error``).
    """
    from exec_sandbox import ALIASES, LANGS, ExecReq, MAX_TIMEOUT, _run

    lang = ALIASES.get(language.lower().strip(), language.lower().strip())
    if lang not in LANGS:
        raise ValueError(f"لغة غير مدعومة: {language}")
    t = max(1, min(int(timeout or 10), MAX_TIMEOUT))
    req = ExecReq(language=lang, code=code, stdin=stdin, timeout=t)
    return dict(_run(lang, LANGS[lang], req, t, time.monotonic()))


def _build(
    passed: bool,
    reason: str,
    *,
    code: str,
    language: str,
    detail: list[dict[str, Any]],
    attempts: int,
) -> VerificationResult:
    """يجمّع الحكم النهائي (نقطة تجميع واحدة لكل مسارات الفشل)."""
    return VerificationResult(
        passed=passed,
        reason=reason,
        code=code,
        language=language,
        attempts=attempts,
        detail=tuple(detail),
    )


def verify_by_execution(
    code: str,
    *,
    language: str = PYTHON,
    tests: str = "",
    stdin: str = "",
    timeout: int = 10,
    expect_exit: int = 0,
    runner: Optional[Runner] = None,
) -> VerificationResult:
    """ينفّذ الكود (مع اختباراته) ويحكم — نجاح فقط بخروج متوقّع مُرصود.

    أنواع الفشل صريحة: ``invalid-tests`` · ``runner-error`` · ``not-verified``
    (خطأ نحوي/تعذّر تحقّق) · ``did-not-run`` · ``timeout`` · ``exit N``.
    لا يوجد مسار يعلن النجاح بلا تنفيذ فعلي.
    """
    lang = language.lower().strip() or PYTHON
    run = runner or sandbox_runner
    started = time.monotonic()
    try:
        source = compose_code(code, tests, lang)
    except ValueError as exc:
        return _build(
            False, f"invalid-tests: {exc}", code=code, language=lang, detail=[], attempts=1
        )
    try:
        raw = run(source, lang, stdin, timeout)
    except Exception as exc:  # صندوق غائب / لغة مرفوضة / أي انفجار داخل المُشغّل
        return _build(
            False, f"runner-error: {exc}", code=code, language=lang, detail=[], attempts=1
        )
    if not isinstance(raw, dict):  # pragma: no cover - دفاعي
        return _build(
            False, "runner-error: نتيجة غير صالحة", code=code, language=lang, detail=[], attempts=1
        )
    detail = [{**raw, "source": source, "elapsed_ms": int((time.monotonic() - started) * 1000)}]
    if not raw.get("verified"):
        return _build(False, "not-verified", code=code, language=lang, detail=detail, attempts=1)
    if not raw.get("ran"):
        return _build(False, "did-not-run", code=code, language=lang, detail=detail, attempts=1)
    if raw.get("timed_out"):
        return _build(False, "timeout", code=code, language=lang, detail=detail, attempts=1)
    if raw.get("exit_code") != expect_exit:
        return _build(
            False, f"exit {raw.get('exit_code')}", code=code, language=lang, detail=detail, attempts=1
        )
    return _build(True, "ok", code=code, language=lang, detail=detail, attempts=1)


def fix_loop(
    task: str,
    code: str,
    *,
    language: str = PYTHON,
    tests: str = "",
    stdin: str = "",
    timeout: int = 10,
    max_attempts: int = 3,
    generate: Optional[Fixer] = None,
    runner: Optional[Runner] = None,
    system: str = "",
) -> VerificationResult:
    """ينفّذ، وعند الفشل يطلب إصلاحاً ويعيد المحاولة — بحدٍّ صارم.

    ``max_attempts`` = عدد **التنفيذات** الكلّي (بما فيها الأولى)، مقيّد
    ``1..MAX_ATTEMPTS``. الإصلاح يقع فقط بين تنفيذتين. ``generate=None`` ⇒
    تنفيذة واحدة والاعتراف بالفشل — لا ننتظر مستشاراً لا وجود له.
    تعذّر الإصلاح (استثناء أو نصّ فارغ) يوقف الحلقة فوراً بلا لفّ.
    """
    limit = max(1, min(int(max_attempts or 1), MAX_ATTEMPTS))
    current = code
    history: list[dict[str, Any]] = []
    done = 0
    for done in range(1, limit + 1):  # pragma: no branch — always breaks on the last pass
        outcome = verify_by_execution(
            current,
            language=language,
            tests=tests,
            stdin=stdin,
            timeout=timeout,
            runner=runner,
        )
        history.extend(outcome.detail)
        if outcome.passed:
            return _build(
                True, "ok", code=current, language=language, detail=history, attempts=done
            )
        if done == limit or generate is None:
            break
        try:
            proposed = generate(task, current, outcome, system)
        except Exception as exc:
            history.append({"repair_error": str(exc)})
            break
        if not isinstance(proposed, str) or not proposed.strip():
            break
        current = proposed
    return _build(
        False, "not-fixed", code=current, language=language, detail=history, attempts=done
    )
