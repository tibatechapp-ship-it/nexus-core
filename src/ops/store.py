"""المخزن الواحد — قاعدة SQLite واحدة بنفس المخططات لكل المكوّنات.

القاعدة المعلنة: كل مكوّن يكتب في **قاعدة بيانات واحدة** بنفس عقود
``contracts.py`` — ما يجعل اللوحة والتقارير موحّدة دون كود لصق.

الجداول الستة:

* ``signals``   — إشارات الرادار (إزالة تكرار بنافذة زمنية معلنة).
* ``verdicts``  — أحكام العزل الثلاثية بأدلتها.
* ``tickets``   — التذاكر بحالاتها وبوابة النشر المحجوبة.
* ``gates``     — نتائج بوابات الفحص (حاجبة واستشارية).
* ``digests``   — الملخصات الواحدة (صباح/مساء/دورة).
* ``audit``     — سجل تدقيق غير محذوف لكل انتقال وقرار.

الهجرة: ``meta.schema_version`` هو رقم المخطط؛ ``_migrate`` يطبّق
الترقيات بالترتيب — الإصدار الأول يبني الجداول، وكل ترقية لاحقة إجراء
معلن قابل للاختبار. المعاملات دائماً داخل ``with self._conn:`` —
الإدخال ذرّي إما كاملًا أو لا شيء.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import weakref
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from src.ops.contracts import (
    ALLOWED_TRANSITIONS,
    FINAL_STATES,
    TICKET_STATES,
    Digest,
    GateResult,
    Signal,
    Ticket,
    Verdict,
    now_iso,
)

__all__ = ["OpsError", "OpsStore", "SCHEMA_VERSION"]

#: إصدار المخطط الواحد — كل ترقية لاحقة إجراء معلن في ``_migrate``.
#: v1: الجداول الستة التأسيسية · v2: جدول شرائح الفهرس ``slices``.
SCHEMA_VERSION = 2


class OpsError(RuntimeError):
    """خطأ صريح في قواعد الطبقة التشغيلية — انتقال غير قانوني أو غياب سجل."""


class _LockedConnection:
    """غلاف اتصال مؤمّن — كل تنفيذ ومعاملة تمر بالقفل الواحد.

    يسمح بجدولة المهام في خيوط متوازية فوق اتصال SQLite واحد دون
    ``check_same_thread`` قاسٍ: القفل RLock قابل لإعادة الدخول، والمعاملة
    تُحمل على الأب القفل حتى لا ينزلق خيط آخر داخل معاملة خيط آخر.
    """

    def __init__(self, conn: sqlite3.Connection,
                 lock: threading.RLock) -> None:
        self._raw = conn
        self._lock = lock

    def execute(self, sql: str,
                params: Sequence[Any] | None = None) -> sqlite3.Cursor:
        """تنفيذ مؤمّن — بلا معاملات يُمرَّر اتصالًا نقيًا لا None."""
        with self._lock:
            if params is None:
                return self._raw.execute(sql)
            return self._raw.execute(sql, params)

    def __enter__(self) -> sqlite3.Connection:
        """فتح معاملة مؤمّنة — القفل يُحمل حتى نهاية الخروج."""
        self._lock.acquire()
        try:
            return self._raw.__enter__()
        except Exception:
            self._lock.release()
            raise

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        """إغلاق المعاملة وتحرير القفل مهما حدث — لا قفل عالق."""
        try:
            self._raw.__exit__(exc_type, exc, tb)  # type: ignore[arg-type]
        finally:
            self._lock.release()


class OpsStore:
    """المخزن الموحّد — واجهة واحدة للجداول الستة وسجل التدقيق.

    ``path`` مسار ملف القاعدة؛ ``:memory:`` مدعوم للاختبارات. الاتصال
    واحد داخل الكائن مع قفل واحد يغلّف كل عمليات القراءة والكتابة —
    فالجدولة المتوازية للمهام آمنة بترتيب صارم، والمعاملات دائمًا
    داخل ``with self._conn:`` — الإدخال ذرّي إما كاملًا أو لا شيء.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._path = Path(path) if path != ":memory:" else None
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        raw = sqlite3.connect(
            str(self._path) if self._path is not None else ":memory:",
            check_same_thread=False,
        )
        raw.row_factory = sqlite3.Row
        self._conn = _LockedConnection(raw, self._lock)
        # Explicit close is supported; finalizer is a last-resort safety net.
        self._connection_finalizer = weakref.finalize(self, raw.close)
        with self._lock:
            self._migrate()

    def close(self) -> None:
        """Close the owned SQLite handle; safe to call more than once."""
        with self._lock:
            if self._connection_finalizer.alive:
                self._connection_finalizer()

    def __enter__(self):
        """Support deterministic resource ownership with a context manager."""
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


    # ── المخطط والهجرة ────────────────────────────────────────────────────

    def _migrate(self) -> None:
        """بناء/ترقية المخطط — الرقم في ``meta`` هو المرجع الوحيد."""
        with self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS meta ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
            current = int(row["value"]) if row else 0
            if current < 1:
                self._create_v1()
            if current < 2:
                self._create_v2()
            if current > SCHEMA_VERSION:
                raise OpsError(
                    f"مخطط القاعدة أحدث من الكود: {current} > {SCHEMA_VERSION}"
                )
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),),
            )

    def _create_v1(self) -> None:
        """الإصدار الأول — الجداول الستة بفهارسها الافتراضية."""
        self._conn.execute(
            "CREATE TABLE signals ("
            "id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL, "
            "url TEXT NOT NULL, published_at TEXT NOT NULL DEFAULT '', "
            "score REAL NOT NULL DEFAULT 0, tags TEXT NOT NULL DEFAULT '[]', "
            "raw_ref TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)"
        )
        self._conn.execute(
            "CREATE TABLE verdicts ("
            "id TEXT PRIMARY KEY, target TEXT NOT NULL, verdict TEXT NOT NULL, "
            "evidence TEXT NOT NULL, confidence REAL NOT NULL, "
            "checks TEXT NOT NULL DEFAULT '{}', ticket_id TEXT, "
            "created_at TEXT NOT NULL)"
        )
        self._conn.execute(
            "CREATE TABLE tickets ("
            "id TEXT PRIMARY KEY, origin TEXT NOT NULL, title TEXT NOT NULL, "
            "branch TEXT NOT NULL DEFAULT '', state TEXT NOT NULL, "
            "report TEXT NOT NULL DEFAULT '{}', publish_allowed INTEGER NOT NULL DEFAULT 0, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        self._conn.execute(
            "CREATE TABLE gates ("
            "id TEXT PRIMARY KEY, tool TEXT NOT NULL, target TEXT NOT NULL, "
            "blocking INTEGER NOT NULL, passed INTEGER NOT NULL, "
            "findings TEXT NOT NULL DEFAULT '[]', ticket_id TEXT, "
            "created_at TEXT NOT NULL)"
        )
        self._conn.execute(
            "CREATE TABLE digests ("
            "id TEXT PRIMARY KEY, kind TEXT NOT NULL, day TEXT NOT NULL, "
            "payload TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)"
        )
        self._conn.execute(
            "CREATE TABLE audit ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, "
            "actor TEXT NOT NULL DEFAULT 'system', action TEXT NOT NULL, "
            "ref TEXT NOT NULL DEFAULT '', details TEXT NOT NULL DEFAULT '{}')"
        )

    def _create_v2(self) -> None:
        """الإصدار الثاني — شرائح فهرس الذكاء بنفس القاعدة الواحدة."""
        self._conn.execute(
            "CREATE TABLE slices ("
            "id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', "
            "acl TEXT NOT NULL DEFAULT 'team:all', body TEXT NOT NULL, "
            "tokens INTEGER NOT NULL, version TEXT NOT NULL DEFAULT 'v1', "
            "ttl_days INTEGER NOT NULL DEFAULT 0, vec TEXT NOT NULL DEFAULT '[]', "
            "created_at TEXT NOT NULL)"
        )

    # ── التدقيق ───────────────────────────────────────────────────────────

    def audit(self, action: str, ref: str = "", details: dict[str, Any] | None = None,
              actor: str = "system") -> None:
        """سجل تدقيق واحد — كل قرار وانتقال يمر من هنا قبل أي شيء آخر."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO audit (at, actor, action, ref, details) "
                "VALUES (?, ?, ?, ?, ?)",
                (now_iso(), actor, action, ref, json.dumps(details or {}, sort_keys=True)),
            )

    def tail_audit(self, limit: int = 20) -> list[dict[str, Any]]:
        """أحدث سجلات التدقيق — الأحدث أولًا، لعرض القرارات الأخيرة."""
        rows = self._conn.execute(
            "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append({
                "id": r["id"], "at": r["at"], "actor": r["actor"],
                "action": r["action"], "ref": r["ref"],
                "details": json.loads(r["details"]),
            })
        return out

    # ── الإشارات ──────────────────────────────────────────────────────────

    def add_signal(self, signal: Signal, dedup_window_days: int = 30) -> bool:
        """تخزين إشارة مع إزالة تكرار — ``False`` إن كان الرابط مكررًا بالنافذة.

        النافذة الافتراضية 30 يومًا: نفس الرابط داخل النافذة يُهمَل مهما
        تغيّرت درجته — التكرار ضجيج لا إشارة. الفحص بالمعرّف أولًا
        (التخزين إلزامي حتميًا)، ثم بالرابط داخل النافذة.
        """
        row = self._conn.execute(
            "SELECT id FROM signals WHERE id = ?", (signal.id,)
        ).fetchone()
        if row:
            return False
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=dedup_window_days)
        ).isoformat()
        row = self._conn.execute(
            "SELECT id FROM signals WHERE url = ? AND created_at >= ?",
            (signal.url, cutoff),
        ).fetchone()
        if row:
            return False
        with self._conn:
            self._conn.execute(
                "INSERT INTO signals (id, source, title, url, published_at, score, "
                "tags, raw_ref, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    signal.id, signal.source, signal.title, signal.url,
                    signal.published_at, signal.score,
                    json.dumps(list(signal.tags), sort_keys=True), signal.raw_ref,
                    signal.created_at,
                ),
            )
        self.audit("signal.stored", signal.id, {"source": signal.source, "score": signal.score})
        return True

    def list_signals(self, day: str | None = None, min_score: float = 0.0,
                     limit: int = 50) -> list[Signal]:
        """إشارات مخزّنة مرتبة بالدرجة — فلترة يومية ودرجة دنيا اختيارية."""
        if day is None:
            rows = self._conn.execute(
                "SELECT * FROM signals WHERE score >= ? ORDER BY score DESC, created_at DESC "
                "LIMIT ?",
                (min_score, int(limit)),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM signals WHERE score >= ? AND substr(created_at, 1, 10) = ? "
                "ORDER BY score DESC, created_at DESC LIMIT ?",
                (min_score, day, int(limit)),
            ).fetchall()
        out: list[Signal] = []
        for r in rows:
            out.append(Signal(
                source=r["source"], title=r["title"], url=r["url"],
                published_at=r["published_at"], score=r["score"],
                tags=tuple(json.loads(r["tags"])), raw_ref=r["raw_ref"],
                id=r["id"], created_at=r["created_at"],
            ))
        return out

    # ── الأحكام ───────────────────────────────────────────────────────────

    def add_verdict(self, verdict: Verdict) -> bool:
        """تخزين حكم — إعادة تخزين نفس الهدف والحكم تُحدّث التذكرة المرتبطة."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO verdicts (id, target, verdict, evidence, confidence, "
                "checks, ticket_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET ticket_id = excluded.ticket_id",
                (
                    verdict.id, verdict.target, verdict.verdict,
                    json.dumps(list(verdict.evidence), sort_keys=True),
                    verdict.confidence, json.dumps(verdict.checks, sort_keys=True),
                    verdict.ticket_id, verdict.created_at,
                ),
            )
        self.audit("verdict.recorded", verdict.id,
                   {"target": verdict.target, "verdict": verdict.verdict})
        return True

    def latest_verdict(self, target: str) -> Verdict | None:
        """أحدث حكم لهدف معين — الأساس في تحديث التذاكر المرتبطة."""
        rows = self._conn.execute(
            "SELECT * FROM verdicts WHERE target = ? ORDER BY created_at DESC LIMIT 1",
            (target,),
        ).fetchall()
        if not rows:
            return None
        r = rows[0]
        return Verdict(
            target=r["target"], verdict=r["verdict"],
            evidence=tuple(json.loads(r["evidence"])), confidence=r["confidence"],
            checks=json.loads(r["checks"]), ticket_id=r["ticket_id"],
            id=r["id"], created_at=r["created_at"],
        )

    # ── التذاكر ───────────────────────────────────────────────────────────

    def next_ticket_id(self) -> str:
        """المعرّف التالي ``T-YYYY-NNN`` — تسلسل سنوي حتمي من المخزن نفسه."""
        year = datetime.now(timezone.utc).year
        rows = self._conn.execute(
            "SELECT id FROM tickets WHERE id LIKE ? ORDER BY id DESC LIMIT 1",
            (f"T-{year}-%",),
        ).fetchall()
        n = int(rows[0]["id"].rsplit("-", 1)[1]) + 1 if rows else 1
        return f"T-{year}-{n:03d}"

    def add_ticket(self, ticket: Ticket) -> Ticket:
        """تخزين تذكرة جديدة بمعرّف متسلسل — المعرّف والفرع يُبنى هنا."""
        if not ticket.id:
            assigned = self.next_ticket_id()
            branch = ticket.branch or f"t/{assigned}"
            ticket = Ticket(
                origin=ticket.origin, title=ticket.title, branch=branch,
                state=ticket.state, report=ticket.report,
                publish_allowed=ticket.publish_allowed, id=assigned,
                created_at=ticket.created_at, updated_at=ticket.updated_at,
            )
        with self._conn:
            self._conn.execute(
                "INSERT INTO tickets (id, origin, title, branch, state, report, "
                "publish_allowed, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ticket.id, ticket.origin, ticket.title, ticket.branch,
                    ticket.state, json.dumps(ticket.report, sort_keys=True),
                    int(ticket.publish_allowed), ticket.created_at, ticket.updated_at,
                ),
            )
        self.audit("ticket.opened", ticket.id,
                   {"origin": ticket.origin, "branch": ticket.branch, "state": ticket.state})
        return ticket

    def ticket_get(self, ticket_id: str) -> Ticket | None:
        """قراءة تذكرة واحدة — ``None`` إن لم توجد."""
        row = self._conn.execute(
            "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
        ).fetchone()
        if not row:
            return None
        return Ticket(
            origin=row["origin"], title=row["title"], branch=row["branch"],
            state=row["state"], report=json.loads(row["report"]),
            publish_allowed=bool(row["publish_allowed"]), id=row["id"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def ticket_list(self, state: str | None = None, limit: int = 100) -> list[Ticket]:
        """تذاكر مرتبة بالأحدث — فلترة حالة واحدة اختيارية."""
        if state is not None:
            rows = self._conn.execute(
                "SELECT * FROM tickets WHERE state = ? ORDER BY id DESC LIMIT ?",
                (state, int(limit)),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM tickets ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [self._row_to_ticket(r) for r in rows]

    def _row_to_ticket(self, r: sqlite3.Row) -> Ticket:
        """بناء عقد التذكرة من صف القاعدة — محوّل واحد لكل القراءات."""
        return Ticket(
            origin=r["origin"], title=r["title"], branch=r["branch"],
            state=r["state"], report=json.loads(r["report"]),
            publish_allowed=bool(r["publish_allowed"]), id=r["id"],
            created_at=r["created_at"], updated_at=r["updated_at"],
        )

    def ticket_advance(self, ticket_id: str, to_state: str, actor: str = "agent",
                       ci_green: bool = False, note: str = "") -> Ticket:
        """انتقال حالة بقواعد مثبتة — الدمج مراجعة بشرية + CI أخضر، بلا استثناء.

        القواعد الثلاث المفروضة هنا:

        1. الانتقال يجب أن يكون في ``ALLOWED_TRANSITIONS`` — ما عدا ذلك خطأ.
        2. الانتقال إلى ``merged`` يتطلّب ``actor`` بشريًا (ليس ``agent``) و
           ``ci_green=True`` — قاعدة «لا دمج دون مراجعة وبوابة».
        3. كل انتقال يكتب سجل تدقيق بملاحظته قبل إعادة التذكرة.
        """
        current = self.ticket_get(ticket_id)
        if current is None:
            raise OpsError(f"تذكرة غير موجودة: {ticket_id}")
        if to_state not in TICKET_STATES:
            raise OpsError(f"حالة هدف غير معروفة: {to_state!r}")
        if to_state not in ALLOWED_TRANSITIONS[current.state]:
            raise OpsError(
                f"انتقال غير قانوني: {current.state} → {to_state} "
                f"(القانوني من {current.state}: {sorted(ALLOWED_TRANSITIONS[current.state])})"
            )
        if to_state == "merged":
            if actor == "agent":
                raise OpsError("الدمج يمنع آليًا — المراجعة بشرية فقط")
            if not ci_green:
                raise OpsError("الدمج يتطلّب CI أخضر — بوابة لا مجاملة")
        with self._conn:
            self._conn.execute(
                "UPDATE tickets SET state = ?, updated_at = ? WHERE id = ?",
                (to_state, now_iso(), ticket_id),
            )
        self.audit("ticket.advance", ticket_id,
                   {"from": current.state, "to": to_state, "ci_green": ci_green,
                    "note": note}, actor=actor)
        updated = self.ticket_get(ticket_id)
        assert updated is not None  # حوى القراءة سابقاً — العقد مضمون داخليًا
        return updated

    def ticket_set_publish(self, ticket_id: str, allowed: bool,
                           actor: str = "agent") -> Ticket:
        """فتح بوابة النشر — مراجعة بشرية فقط، وحالة غير نهائية مرفوضة."""
        current = self.ticket_get(ticket_id)
        if current is None:
            raise OpsError(f"تذكرة غير موجودة: {ticket_id}")
        if actor == "agent":
            raise OpsError("فتح النشر قرار بشري — لا وكيل يفتحه")
        if allowed and current.state not in {"reviewed", "merged"}:
            raise OpsError(
                f"فتح النشر يتطلب حالة reviewed/merged، والحالة: {current.state}"
            )
        with self._conn:
            self._conn.execute(
                "UPDATE tickets SET publish_allowed = ?, updated_at = ? WHERE id = ?",
                (int(allowed), now_iso(), ticket_id),
            )
        self.audit("ticket.publish_gate", ticket_id, {"allowed": allowed}, actor=actor)
        updated = self.ticket_get(ticket_id)
        assert updated is not None
        return updated

    def stale_tickets(self, days: int = 14) -> list[Ticket]:
        """تذاكر خاملة غير نهائية — لم تتحرك منذ ``days`` يومًا."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            "SELECT * FROM tickets WHERE updated_at < ? "
            "AND state NOT IN ("
            + ",".join("?" for _ in FINAL_STATES) + ") ORDER BY updated_at ASC",
            (cutoff, *sorted(FINAL_STATES)),
        ).fetchall()
        return [self._row_to_ticket(r) for r in rows]

    # ── البوابات ──────────────────────────────────────────────────────────

    def add_gate(self, gate: GateResult) -> GateResult:
        """تخزين نتيجة بوابة — الحاجبة الفاشلة تفتح تذكرة في ``webqa`` لا هنا."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO gates (id, tool, target, blocking, passed, findings, "
                "ticket_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    gate.id, gate.tool, gate.target, int(gate.blocking),
                    int(gate.passed),
                    json.dumps([dict(f) for f in gate.findings], sort_keys=True),
                    gate.ticket_id, gate.created_at,
                ),
            )
        self.audit("gate.recorded", gate.id,
                   {"tool": gate.tool, "passed": gate.passed, "blocking": gate.blocking})
        return gate

    def gate_set_ticket(self, gate_id: str, ticket_id: str) -> bool:
        """ربط تذكرة ببوابة مخزّنة — التحديث على السجل نفسه لا إعادة إدخال."""
        with self._conn:
            cur = self._conn.execute(
                "UPDATE gates SET ticket_id = ? WHERE id = ?", (ticket_id, gate_id)
            )
        if cur.rowcount == 0:
            raise OpsError(f"بوابة غير موجودة: {gate_id}")
        self.audit("gate.linked", gate_id, {"ticket_id": ticket_id})
        return True

    def list_gates(self, target: str | None = None, limit: int = 50) -> list[GateResult]:
        """بوابات مرتبة بالأحدث — فلترة هدف اختيارية."""
        if target is None:
            rows = self._conn.execute(
                "SELECT * FROM gates ORDER BY created_at DESC LIMIT ?", (int(limit),)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM gates WHERE target = ? ORDER BY created_at DESC LIMIT ?",
                (target, int(limit)),
            ).fetchall()
        out: list[GateResult] = []
        for r in rows:
            out.append(GateResult(
                tool=r["tool"], target=r["target"], blocking=bool(r["blocking"]),
                passed=bool(r["passed"]), findings=tuple(json.loads(r["findings"])),
                ticket_id=r["ticket_id"], id=r["id"], created_at=r["created_at"],
            ))
        return out

    # ── الملخصات ──────────────────────────────────────────────────────────

    def add_digest(self, digest: Digest) -> Digest:
        """تخزين ملخص — نفس (النوع، اليوم) يستبدل السابق: ملخص واحد لا تراكم."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO digests (id, kind, day, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, "
                "created_at = excluded.created_at",
                (digest.id, digest.kind, digest.day,
                 json.dumps(digest.payload, sort_keys=True), digest.created_at),
            )
        self.audit("digest.recorded", digest.id, {"kind": digest.kind, "day": digest.day})
        return digest

    def latest_digest(self, kind: str | None = None) -> Digest | None:
        """أحدث ملخص — بالنوع أو عمومًا؛ لا شيء إن كان المخزن فارغًا."""
        if kind is None:
            rows = self._conn.execute(
                "SELECT * FROM digests ORDER BY created_at DESC LIMIT 1"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM digests WHERE kind = ? ORDER BY created_at DESC LIMIT 1",
                (kind,),
            ).fetchall()
        if not rows:
            return None
        r = rows[0]
        return Digest(
            kind=r["kind"], day=r["day"], payload=json.loads(r["payload"]),
            id=r["id"], created_at=r["created_at"],
        )

    # ── العدّ اللوحوي ─────────────────────────────────────────────────────

    def counts(self) -> dict[str, int]:
        """أعداد الجداول — أساس لقطة اللوحة والملخصات."""
        out: dict[str, int] = {}
        for table in ("signals", "verdicts", "tickets", "gates", "digests", "slices"):
            row = self._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            out[table] = int(row["n"])
        return out

    def ticket_state_counts(self) -> dict[str, int]:
        """عدد التذاكر لكل حالة — صف اللوحة الواحد لحالة خط التذاكر."""
        rows = self._conn.execute(
            "SELECT state, COUNT(*) AS n FROM tickets GROUP BY state ORDER BY state"
        ).fetchall()
        return {r["state"]: int(r["n"]) for r in rows}

    def close(self) -> None:
        """إغلاق الاتصال — للاستدعاء الصريح في نهاية العمليات الطويلة."""
        with self._lock:
            self._conn._raw.close()
