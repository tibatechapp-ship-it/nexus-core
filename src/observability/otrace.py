"""التتبّع العميق — جلسات JSONL بمعرّفات متوافقة مفاهيميًا مع OTel.

المعلم (docs/V2_ROADMAP.md م3 — ض2):
    كل جلسة مجلس/سير تُسجَّل كشجرة spans في ملف JSONL واحد
    ``<traces_dir>/<trace_id>.jsonl`` بحقول::

        schema    — "nexus.trace/v1" (عقد الاختبار يعتمده)
        ts        — ISO-8601 UTC لحظة اكتمال الـ span
        trace_id  — 32 hex (نمط OTel)
        span_id   — 16 hex (نمط OTel)
        parent_span_id — 16 hex أو "" للجذر
        seq       — ترتيب الكتابة (استقرار الفرز في replay)
        name      — اسم الخطوة ("council.deliberate" مثلاً)
        agent     — من نفّذها
        duration_ms — مدة الـ span بالمللي ثانية
        outcome   — "ok" أو "error"
        attributes — بيانات وصفية آمنة فقط (بلا محتوى مستخدم)

الخصوصية افتراضية:
    * لا يُصدَّر أي شيء خارج الجهاز إلا إذا فعّل المستخدم
      ``NEXUS_OTLP_ENDPOINT`` صراحةً — المُصدِّر معطَّل افتراضيًا.
    * مرشّح خصوصية دفاعي: مفاتيح السمات مثل ``prompt``/``content``
      تُسقَط حتى لو مرّرت بالخطأ (داخل ``_FORBIDDEN_ATTR_KEYS``).

الدوران والضغط:
    تجاوز الملف ``MAX_BYTES`` يُدوّره إلى ``<name>.1`` ثم يضغطه zlib
    إلى ``.1.z`` — ``read_spans`` يقرأ الأسهم والمدور المضغوط بلا فرق.

الاستخدام:
    from src.observability.otrace import DeepTracer
    tracer = DeepTracer()
    with tracer.session() as t:
        with t.span("council.deliberate", agent="council"):
            with t.span("council.round", attributes={"round": 1}):
                ...
    spans = replay_steps(tracer.path)   # للـ PWA بعد الحدث
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]

#: نسخة المخطط — أي تغيير حقلي يمرّ عبر مراجعة عقد (docs/CONTRACTS.md).
TRACE_SCHEMA = "nexus.trace/v1"

#: الحقول الإلزامية في كل سطر span (عقد الاختبار يعتمدها).
REQUIRED_SPAN_FIELDS = (
    "schema", "ts", "start_ts", "trace_id", "span_id", "parent_span_id",
    "seq", "name", "agent", "duration_ms", "outcome", "attributes",
)

#: سقف ملف الجلسة قبل التدوير والضغط (5 ميغابايت).
MAX_BYTES = 5 * 1024 * 1024

#: مفاتيح سمات ممنوعة دفاعيًا — محتوى مستخدم لا يعيش في التتبّع أبداً.
_FORBIDDEN_ATTR_KEYS = frozenset({
    "prompt", "content", "messages", "text", "input", "output",
    "question", "answer", "response", "body", "transcript",
})

#: قيم السمات المسموحة — scalars فقط (لا حاويات قد تحوي PII).
_ALLOWED_ATTR_TYPES = (str, int, float, bool)


def new_trace_id() -> str:
    """معرّف تتبّع OTel-نمط: 16 بايت عشوائية = 32 hex."""
    return secrets.token_hex(16)


def new_span_id() -> str:
    """معرّف span بنمط OTel: 8 بايت عشوائية = 16 hex."""
    return secrets.token_hex(8)


def traces_dir() -> Path:
    """مجلد الجلسات — البيئة أولاً ثم ``<ROOT>/runs/traces``."""
    env = os.environ.get("NEXUS_TRACES_DIR")
    if env:
        return Path(env)
    return ROOT / "runs" / "traces"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sanitize_attributes(attrs: dict[str, Any] | None) -> dict[str, Any]:
    """نظّف سمات الـ span: scalars فقط، والممنوع يُسقَط صامتًا."""
    clean: dict[str, Any] = {}
    if not attrs:
        return clean
    for key, value in attrs.items():
        k = str(key)
        if k.lower() in _FORBIDDEN_ATTR_KEYS:
            continue
        if isinstance(value, _ALLOWED_ATTR_TYPES):
            clean[k] = value
    return clean


class OTLPExporter:
    """مُصدِّر OTLP/JSON اختياري — urllib فقط، معطَّل افتراضيًا.

    لا يعمل إلا إذا ضُبط ``NEXUS_OTLP_ENDPOINT`` (الخوصصة افتراضية).
    كل فشل شبكة يُبتلع — التتبّع المحلي لا يتأثر أبداً (best-effort).
    """

    def __init__(
        self,
        endpoint: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 2.0,
    ) -> None:
        self.endpoint = endpoint or os.environ.get("NEXUS_OTLP_ENDPOINT", "")
        self.headers = headers or {}
        self.timeout = timeout
        self.enabled = bool(self.endpoint)

    def _payload(self, spans: list[dict[str, Any]]) -> dict[str, Any]:
        """حوّل spans محلية إلى OTLP/JSON (resourceSpans)."""
        otel_spans = []
        for s in spans:
            attrs = [
                {"key": k, "value": {"stringValue": str(v)}}
                for k, v in s.get("attributes", {}).items()
            ]
            otel_spans.append({
                "traceId": s["trace_id"],
                "spanId": s["span_id"],
                "parentSpanId": s.get("parent_span_id", "") or "",
                "name": s.get("name", "span"),
                "kind": "SPAN_KIND_INTERNAL",
                "startTimeUnixNano": str(s.get("_start_ns", 0)),
                "endTimeUnixNano": str(s.get("_end_ns", 0)),
                "attributes": attrs,
                "status": {
                    "code": "STATUS_CODE_OK" if s.get("outcome") == "ok"
                    else "STATUS_CODE_ERROR",
                },
            })
        return {"resourceSpans": [{
            "resource": {"attributes": [
                {"key": "service.name",
                 "value": {"stringValue": "nexus-core"}},
            ]},
            "scopeSpans": [{
                "scope": {"name": "nexus.observability",
                          "version": TRACE_SCHEMA},
                "spans": otel_spans,
            }],
        }]}

    def export(self, spans: list[dict[str, Any]]) -> bool:
        """أرسل دفعة spans — True نجاح؛ أي فشل = False بلا استثناء."""
        if not self.enabled or not spans:
            return False
        try:
            import urllib.request

            body = json.dumps(self._payload(spans)).encode("utf-8")
            req = urllib.request.Request(
                self.endpoint, data=body, method="POST",
                headers={
                    "Content-Type": "application/json",
                    **self.headers,
                },
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return bool(200 <= getattr(resp, "status", 200) < 300)
        except Exception:
            return False


class _Span:
    """span حيّ داخل جلسة — يُسجَّل عند الخروج من السياق."""

    __slots__ = (
        "trace_id", "span_id", "parent_span_id", "name", "agent",
        "attributes", "outcome", "seq", "start_ts", "_start_ns", "_t0",
    )

    def __init__(
        self, trace_id: str, span_id: str, parent_span_id: str,
        name: str, agent: str, attributes: dict[str, Any] | None,
        seq: int,
    ) -> None:
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.name = name
        self.agent = agent
        self.attributes = sanitize_attributes(attributes)
        self.outcome = "ok"
        self.seq = seq
        self._start_ns = time.time_ns()
        self.start_ts = datetime.fromtimestamp(
            self._start_ns / 1_000_000_000,
            tz=timezone.utc).isoformat(timespec="milliseconds")
        self._t0 = time.perf_counter()


class DeepTracer:
    """متتبّع جلسة واحد = trace_id واحد = ملف JSONL واحد.

    خيط-آمن (قفل داخلي). الكتابة best-effort: فشل القرص لا يُسقط
    العمل المُتتبَّع.
    """

    def __init__(self, session_dir: Path | None = None) -> None:
        self._dir = session_dir or traces_dir()
        self._lock = threading.Lock()
        self._seq = 0
        self._trace_id = ""
        self._path: Path | None = None
        self._stack: list[str] = []
        self._pending: list[dict[str, Any]] = []
        self.exporter = OTLPExporter()

    # ── جلسة ──────────────────────────────────────────────────────
    @contextmanager
    def session(self) -> Iterator["DeepTracer"]:
        """افتح جلسة تتبّع جديدة (trace_id جديد + ملف جديد)."""
        self._trace_id = new_trace_id()
        self._path = self._dir / f"{self._trace_id}.jsonl"
        self._seq = 0
        self._stack = []
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._path = None
        try:
            yield self
        finally:
            self._flush_otlp()

    @property
    def trace_id(self) -> str:
        return self._trace_id

    @property
    def path(self) -> Path | None:
        return self._path

    # ── spans ─────────────────────────────────────────────────────
    @contextmanager
    def span(
        self,
        name: str,
        agent: str = "",
        attributes: dict[str, Any] | None = None,
    ) -> Iterator[_Span]:
        """سجّل span (يتداخل تلقائيًا مع الأب الحالي)."""
        parent = self._stack[-1] if self._stack else ""
        with self._lock:
            self._seq += 1
            seq = self._seq
        s = _Span(self._trace_id, new_span_id(), parent, name,
                  agent or "unknown", attributes, seq)
        self._stack.append(s.span_id)
        try:
            yield s
        except Exception:
            s.outcome = "error"
            raise
        finally:
            self._stack.pop()
            self._record(s)

    # ── كتابة ─────────────────────────────────────────────────────
    def _record(self, s: _Span) -> None:
        duration_ms = round((time.perf_counter() - s._t0) * 1000.0, 3)
        # إعادة تصفية دفاعية عند الكتابة — أي تعديل للسمات بعد
        # الإنشاء يمرّ بالمرشّح ذاته (المفتاح الممنوع لا يُكتب أبداً).
        s.attributes = sanitize_attributes(s.attributes)
        with self._lock:
            payload: dict[str, Any] = {
                "schema": TRACE_SCHEMA,
                "ts": _utc_iso(),
                "start_ts": s.start_ts,
                "trace_id": s.trace_id,
                "span_id": s.span_id,
                "parent_span_id": s.parent_span_id,
                "seq": s.seq,
                "name": s.name,
                "agent": s.agent,
                "duration_ms": duration_ms,
                "outcome": s.outcome,
                "attributes": s.attributes,
            }
            live = dict(payload)
            live["_start_ns"] = s._start_ns
            live["_end_ns"] = time.time_ns()
            self._pending.append(live)
            self._write_line(payload)

    def _write_line(self, payload: dict[str, Any]) -> None:
        if self._path is None:
            return
        try:
            if self._path.exists() and self._path.stat().st_size >= MAX_BYTES:
                _rotate(self._path)
            line = json.dumps(payload, ensure_ascii=False)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    def _flush_otlp(self) -> None:
        """أرسل ما تجمّع للـ OTLP إن كان مفعّلًا (best-effort)."""
        if not self.exporter.enabled:
            self._pending.clear()
            return
        batch = list(self._pending)
        self._pending.clear()
        if batch:
            self.exporter.export(batch)


def _rotate(path: Path) -> None:
    """دوّر الملف: ``.jsonl`` → ``.1`` → اضغطه zlib إلى ``.1.z``."""
    try:
        backup = path.with_name(path.name + ".1")
        if backup.exists():
            compressed = path.with_name(path.name + ".1.z")
            compressed.write_bytes(zlib.compress(backup.read_bytes(), 6))
            backup.unlink()
        path.replace(backup)
    except OSError:
        pass


# ═══ القراءة / Replay ════════════════════════════════════════════

def read_spans(path: Path | str) -> list[dict[str, Any]]:
    """اقرأ كل spans جلسة: الملف الحي + المدور المضغوط، بترتيب seq."""
    p = Path(path)
    spans: list[dict[str, Any]] = []

    def _parse(text: str) -> None:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                spans.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # سطر تالف لا يكسر الـ replay

    # التدوير يترك: ``<name>.1.z`` (الأقدم) ثم ``<name>.1`` ثم الحيّ.
    try:
        zpath = p.with_name(p.name + ".1.z")
        if zpath.exists():
            _parse(zlib.decompress(zpath.read_bytes()).decode("utf-8"))
        prev = p.with_name(p.name + ".1")
        if prev.exists():
            _parse(prev.read_text(encoding="utf-8"))
        if p.exists():
            _parse(p.read_text(encoding="utf-8"))
    except OSError:
        pass
    spans.sort(key=lambda s: s.get("seq", 0))
    return spans


def list_sessions(session_dir: Path | str | None = None) -> list[dict[str, Any]]:
    """اجرد جلسات التتبّع المتاحة — الأحدث أولًا."""
    d = Path(session_dir) if session_dir else traces_dir()
    out: list[dict[str, Any]] = []
    try:
        files = sorted(d.glob("*.jsonl"), key=lambda f: f.stat().st_mtime,
                       reverse=True)
    except OSError:
        return out
    for f in files:
        try:
            stat = f.stat()
            out.append({
                "session_id": f.stem,
                "ts": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc).isoformat(
                    timespec="seconds"),
                "bytes": stat.st_size,
            })
        except OSError:
            continue
    return out


def replay_steps(path: Path | str) -> list[dict[str, Any]]:
    """خطوات جاهزة للعرض في PWA — نفس read_spans (اسم معبّر)."""
    return read_spans(path)
