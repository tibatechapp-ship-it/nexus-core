"""سجل أثر معياري (Structured Trace Logs) — سطر JSON لكل تشغيل.

المعلم (Week-2 من خارطة المنتَجة):
    كل تشغيل وكيل/مجلس يكتب سطر JSON واحداً في ``runs/trace.jsonl`` بالحقول:
        ts          — ISO-8601 بتوقيت UTC (لحظة اكتمال الحدث)
        agent       — من فعلها (وكيل، مجلس، مشرف…)
        tool        — ماذا استخدم (الطريقة/المسار/الاستراتيجية)
        duration_ms — مدة التشغيل بالمللي ثانية (>= 0)
        outcome     — "ok" أو "error"
    وحقول إضافية اختيارية دون محتوى المستخدم (لا prompts — بلا PII).

الضمانات:
    * الكتابة best-effort: أي فشل تتبّع لا يُسقط التشغيل المُتتبَّع أبداً.
    * خيط-آمن (قفل واحد) + تدوير حجم بسيط (فيل واحد احتياطي .1) لسقف القرص.
    * stdlib فقط — يعمل على الهاتف مثل باقي النواة.
    * المسار قابل للتوجيه عبر NEXUS_TRACE_PATH (اختبارات وبيئات نشر).

الاستخدام:
    from src.observability.trace import trace_context
    extra: dict = {"tool_detail": "build"}
    with trace_context("code-reviewer", "run", extra):
        result = agent.run(prompt)
    extra["outcome"] = "ok" if result.get("ok") else "error"  # تجاوز اختياري
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]

#: الحقول الإلزامية في كل سطر أثر (عقد الاختبار يعتمدها).
REQUIRED_FIELDS = ("ts", "agent", "tool", "duration_ms", "outcome")

#: السقف قبل تدوير الملف إلى ``trace.jsonl.1`` (5 ميغابايت افتراضياً).
MAX_BYTES = 5 * 1024 * 1024

_lock = threading.Lock()

_RotationError = OSError


def trace_path() -> Path:
    """مسار ملف الأثر — البيئة أولاً ثم ``<ROOT>/runs/trace.jsonl``."""
    env = os.environ.get("NEXUS_TRACE_PATH")
    if env:
        return Path(env)
    return ROOT / "runs" / "trace.jsonl"


def _rotate_if_needed(path: Path) -> None:
    """دوّر إلى ``.1`` إن تجاوز الملف السقف — فشل التدوير لا يمنع الكتابة."""
    try:
        if path.exists() and path.stat().st_size >= MAX_BYTES:
            backup = path.with_name(path.name + ".1")
            if backup.exists():
                backup.unlink()
            path.replace(backup)
    except OSError:
        pass


def _write_line(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False, sort_keys=False)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def trace_event(
    agent: str,
    tool: str,
    outcome: str = "ok",
    duration_ms: float | None = None,
    **extra: Any,
) -> bool:
    """اكتب حدث أثر واحداً — يعيد True عند نجاح الكتابة، ولا يرفع أبداً.

    الحقول الإلزامية تُملأ هنا دائماً؛ أي حقول إضافية تُمرر ككلمات مفتاحية
    (تُقص قيمها النصية إلى 200 محرف، وتُسقط None).
    """
    try:
        if duration_ms is None:
            duration_ms = 0.0
        duration_ms = round(max(0.0, float(duration_ms)), 3)
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "agent": str(agent)[:120],
            "tool": str(tool)[:120],
            "duration_ms": duration_ms,
            "outcome": str(outcome)[:40] or "ok",
        }
        for key, val in extra.items():
            if val is None:
                continue
            if isinstance(val, (int, float, bool)):
                payload[str(key)] = val
            else:
                payload[str(key)] = str(val)[:200]
        path = trace_path()
        with _lock:
            _rotate_if_needed(path)
            _write_line(path, payload)
        return True
    except Exception:  # noqa: BLE001 — التتبع لا يُسقط التشغيل أبداً
        return False


@contextmanager
def trace_context(
    agent: str, tool: str, extra: dict[str, Any] | None = None
) -> Iterator[dict[str, Any]]:
    """قِس مدة الكتلة واكتب الحدث تلقائياً (ok / error).

    * استثناء الكتلة يُعاد كما هو — السياق لا يبتلع الأخطاء أبداً.
    * فشل كتابة التتبع لا يُسقط الكتلة ولا يستبدل استثناءها.
    * مرّر قاموساًMutable وعدّله داخل الكتلة (مثل tool/outcome الفعلي).
    """
    own = extra if extra is not None else {}
    start = time.perf_counter()
    try:
        yield own
    except BaseException as exc:
        _emit(agent, tool, own, start, error=exc)
        raise
    _emit(agent, tool, own, start, error=None)


def _emit(
    agent: str,
    tool: str,
    extra: dict[str, Any],
    start: float,
    *,
    error: BaseException | None,
) -> None:
    duration_ms = (time.perf_counter() - start) * 1000.0
    fields: dict[str, Any] = dict(extra)
    outcome = str(fields.pop("outcome", "") or ("ok" if error is None else "error"))
    if error is not None:
        fields.setdefault("error", type(error).__name__)
    try:
        trace_event(
            agent=str(fields.pop("agent", agent)),
            tool=str(fields.pop("tool", tool)),
            outcome=outcome,
            duration_ms=duration_ms,
            **fields,
        )
    except Exception:  # noqa: BLE001 — حماية مزدوجة: لا أثر على المسار المُتتبَّع
        pass


def read_recent(limit: int = 20) -> list[dict[str, Any]]:
    """آخر ``limit`` حدثاً بترتيب زمني صاعد — يتسامح مع الأسطر التالفة.

    لا يرفع استثناءات: ملف غائب/تالف = قائمة فارغة (مناسب للوحة قراءة-فقت).
    """
    limit = max(1, min(int(limit), 200))
    try:
        path = trace_path()
        if not path.exists():
            return []
        with _lock:
            raw = path.read_text(encoding="utf-8", errors="replace")
        events: list[dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict):
                events.append(ev)
        return events[-limit:]
    except Exception:  # noqa: BLE001 — القراءة قراءة-فقت: لا ترفع أبداً
        return []
