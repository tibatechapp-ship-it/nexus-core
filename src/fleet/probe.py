"""Fleet Probe — حِمل الاستدعاء الآمن أوفلاين لوكلاء novamind.

هذا هو تنفيذ بنود ب1.1 وب1.2 من خطة التحسين (v1.49.0):

* **عقد التهيئة أوفلاين**: كل وكلاء novamind الـ79 يُبنون بلا وسائط إلزامية
  (قيم افتراضية معلنة) وبلا شبكة — أي وكيل يكسر هذا العقد تسقط درجته آلياً
  (مكوّن الاستدعاء = 0) ويُعلن سببه في التقرير، ولا يُجبر على «النجاح».
* **الاستدعاء بطيء زائف معلن**: ``mode: "fake-clock"`` — لا LLM حقيقي ولا
  شبكة؛ ما يُقاس هو زمن الاستدعاء المحلي المحدود فوق المدخلات الحميدة.

سلّم المدخلات المعلن لكل وسيط إلزامي (أول ما ينجح يُعتمد ويُسجَّل):

1. ``"ping"`` — الوسيط المعرَّف ``str`` أو غير المعرَّف.
2. ``{}`` — للأجل غير المعرَّف الذي يقرأ ``.get`` (أنماط المدراء).
3. ``None`` — آخر محاولة، ونتيجتها إن فشلت تُعلن كسبب.

الحالات المعلنة التي لا تُستدعى عمداً:

* ``BLOCKING_MAIN_FUNCTIONS`` — دوال حلقات لا نهائية بالتصميم
  (``run_forever``): استدعاؤها يعلّق القياس، فتُقاس بالبناء وحده.
* الوكلاء بلا ``main_function`` قابلة للوصول (بعض المدراء يُدارون من الخارج
  بلا عقد استدعاء): حِمل «بناء فقط» معلن.

مكوّنات النتيجة المعلنة: ``probe`` (نوع الحِمل)، ``init_ok``، ``init_ms``،
``call_ok``، ``run_ms`` (غير-``null`` طالما البناء نجح — اختبار يمنع عودة
``null`` للأسطول novamind كاملاً)، ``reason`` (قائمة أسباب صادقة).

المهلة: 10 ثوانٍ لكل محاولة عبر ``SIGALRM`` في الخيط الرئيسي فقط — خارج
الخيط الرئيسي يُترك الاستدعاء بلا مهلة (معلَن) لأن ``SIGALRM`` قيوده الخيط
الرئيسي وحده على لينكس.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import signal
import threading
import time
from typing import Any

__all__ = ["probe_agent", "PROBE_TIMEOUT_S", "BLOCKING_MAIN_FUNCTIONS", "PROBE_MODE"]

#: علم النمط المعلن — كل زمن يصدر من هذا القياس هو بطيء زائف (بلا شبكة).
PROBE_MODE = "fake-clock"

#: المهلة القصوى لكل محاولة (بناء أو استدعاء) بالثواني.
PROBE_TIMEOUT_S = 10.0

#: دوال رئيسية مانعة بالتصميم (حلقات لا نهائية) — تُقاس بالبناء وحده.
BLOCKING_MAIN_FUNCTIONS = frozenset({"run_forever"})

#: سلّم المدخلات الحميدة للوسيط غير المعرَّف — بالترتيب، أول نجاح يُعتمد.
_UNTYPED_LADDER: tuple[tuple, ...] = (("ping",), ({},), (None,))


class _ProbeTimeout(Exception):
    """استثناء المهلة الداخلية — يُرصد ولا يُنشر خارج الحِمل."""


def _arm() -> None:
    """تسليح المهلة في الخيط الرئيسي فقط (قيود SIGALRM معلنة)."""
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGALRM, _handler)
        signal.setitimer(signal.ITIMER_REAL, PROBE_TIMEOUT_S)


def _handler(signum: int, frame: Any) -> None:
    raise _ProbeTimeout()


def _disarm() -> None:
    if threading.current_thread() is threading.main_thread():
        signal.setitimer(signal.ITIMER_REAL, 0.0)


def _ensure_src_path() -> None:
    """وحدات novamind تُستورد باسم ``novamind.*`` — ضمّد ``src/`` مرة واحدة."""
    import sys
    from pathlib import Path

    src = str(Path(__file__).resolve().parents[2] / "src")
    if src not in sys.path:
        sys.path.append(src)


def _stub_for(annotation: Any, module: Any) -> tuple | None:
    """بناء stub من dataclass بحقول ``str`` إلزامية (نمط ``Alert``)."""
    real = annotation if isinstance(annotation, type) else None
    if real is None:
        name = str(annotation).strip("'")
        real = getattr(module, name, None)
    if real is None or not dataclasses.is_dataclass(real):
        return None
    kwargs: dict[str, str] = {}
    for f in dataclasses.fields(real):
        if f.type in (str, "str"):
            kwargs[f.name] = "ping"
    try:
        return (real(**kwargs),)
    except Exception:  # noqa: BLE001 — الـstub الفاشل يعني سلّم المدخلات
        return None


def _build_attempts(fn: Any, module: Any) -> list[tuple]:
    """قائمة محاولات الاستدعاء المعلنة من توقيع الدالة."""
    required = [
        p
        for p in inspect.signature(fn).parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if not required:
        return [()]
    if len(required) >= 2:
        return [("ping",) * len(required), ("ping", "ping.py")]
    ann = required[0].annotation
    if ann is str or ann == "str":
        return [("ping",)]
    stub = _stub_for(ann, module)
    if stub is not None:
        return [stub]
    return list(_UNTYPED_LADDER)


def probe_agent(record: Any) -> dict:
    """حِمل وكيل novamind واحد: بناء أوفلاين + استدعاء محدود معلن.

    يُرجع قاموساً معلناً بأزمنة ``fake-clock`` وأسباب صادقة؛ لا يرفع
    استثناءات إطلاقاً — كل فشل بيان في ``reason`` لا انفجار.
    """
    try:
        return _probe_agent_impl(record)
    except Exception as exc:  # noqa: BLE001 — عقد الحِمل: لا استثناءات إطلاقاً
        return {
            "mode": PROBE_MODE,
            "probe": "probe-error",
            "init_ok": False,
            "init_ms": None,
            "call_ok": False,
            "run_ms": None,
            "input_used": None,
            "result_type": None,
            "reason": [f"probe: {type(exc).__name__}: {exc}"[:160]],
        }


def _probe_agent_impl(record: Any) -> dict:
    """تنفيذ الحِمل الفعلي — يستدعيه ``probe_agent`` بحارس شامل."""
    reasons: list[str] = []
    out: dict = {
        "mode": PROBE_MODE,
        "probe": "import-only",
        "init_ok": False,
        "init_ms": None,
        "call_ok": False,
        "run_ms": None,
        "input_used": None,
        "result_type": None,
        "reason": reasons,
    }
    if record.framework != "novamind" or not record.module or not record.symbol:
        reasons.append("probe: not a novamind record with module/symbol")
        return out
    _ensure_src_path()
    try:
        module = importlib.import_module(record.module)
    except Exception as exc:  # noqa: BLE001 — الفشل يُعلن لا يُنشر
        reasons.append(f"import: {type(exc).__name__}: {exc}"[:160])
        return out

    entry = getattr(module, record.symbol, None)
    if entry is None:
        reasons.append(f"entrypoint: {record.symbol!r} missing")
        return out

    # 1) البناء الأوفلاين — عقد التهيئة (ب1.1)
    _arm()
    t0 = time.perf_counter()
    try:
        obj = entry()
        out["init_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        out["init_ok"] = True
    except _ProbeTimeout:
        out["init_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        reasons.append("construct: timeout 10s")
        _disarm()
        out["probe"] = "construct-timeout"
        return out
    except Exception as exc:  # noqa: BLE001
        out["init_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        reasons.append(f"construct: {type(exc).__name__}: {exc}"[:160])
        _disarm()
        out["probe"] = "construct-failed"
        return out
    finally:
        _disarm()

    # 2) الاستدعاء المحدود — ب1.2
    main_fn = record.main_function or ""
    fn = getattr(obj, main_fn, None) if main_fn else None
    where = "method"
    if fn is None and main_fn:
        fn = getattr(module, main_fn, None)
        where = "module"
    if fn is None or main_fn in BLOCKING_MAIN_FUNCTIONS:
        # حِمل «بناء فقط» — المدراء بلا عقد استدعاء يُقاسون بالبناء وحده
        out["probe"] = "construct-only(blocking)" if main_fn else "construct-only"
        out["run_ms"] = out["init_ms"]
        reasons.append(
            f"invoke: no invocable main_function ({main_fn!r} blocking)"
            if main_fn
            else "invoke: no invocable main_function (managed externally)"
        )
        return out

    attempts = _build_attempts(fn, module)
    last_error = ""
    for attempt in attempts:
        _arm()
        t1 = time.perf_counter()
        try:
            result = fn(*attempt)
            out["run_ms"] = round((time.perf_counter() - t1) * 1000, 2)
            out["call_ok"] = True
            out["input_used"] = repr(attempt[0])[:40]
            out["result_type"] = type(result).__name__
            out["probe"] = f"call:{where}"
            return out
        except _ProbeTimeout:
            out["run_ms"] = round((time.perf_counter() - t1) * 1000, 2)
            last_error = "timeout 10s"
        except Exception as exc:  # noqa: BLE001 — كل محاولة تُعلن
            out["run_ms"] = round((time.perf_counter() - t1) * 1000, 2)
            last_error = f"{type(exc).__name__}: {exc}"[:120]
        finally:
            _disarm()
    out["probe"] = f"call-failed:{where}"
    reasons.append(f"invoke: all ladder inputs failed ({last_error})")
    return out
