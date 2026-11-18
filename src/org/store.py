"""متجر التنظيم — قاعدة واحدة لكل سجلات الأقسام الثمانية.

القواعد المعلنة:

* **مخزن واحد**: كل ما ينتجه خط الأنابيب (مهام، مراجعات، نتائج فحص،
  ادعاءات، أدلة، موافقات، دروس، مقاييس) في قاعدة SQLite واحدة —
  اللوحة والتقارير تقرأه ولا تعرف تفاصيل الأقسام.
* **تدقيق غير محذوف**: كل انتقال طور وكل قرار موافقة وكل تغيير حالة
  مهمة فرعية يكتب سطرًا في ``audit`` — لا شيء يعدّله ولا يحذفه.
* **فرض آلة الحالات في المتجر**: انتقال طور غير قانوني رفع واضح —
  العقد مجمّد والمتجر هو حارس الانتقال الوحيد.
* **معرّفات حتمية**: ``new_id`` من محتوى السجل — نفس المهمة بذات
  العنوان والهدف تعطي نفس المعرّف، والإدخال مكررٌ آمن (idempotent).
* **هجرة معلنة**: ``meta.schema_version`` مرجع المخطط؛ كل ترقية إجراء
  معلن في ``_migrate``. المعاملات دائمًا داخل ``with self._conn:``.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.org.contracts import (
    ALLOWED_PHASE_TRANSITIONS,
    Approval,
    Claim,
    Evidence,
    Finding,
    Lesson,
    Mission,
    Review,
    TaskResult,
    TaskSpec,
    new_id,
)

__all__ = ["OrgError", "OrgStore", "ORG_SCHEMA_VERSION"]

#: إصدار مخطط متجر التنظيم — كل ترقية لاحقة إجراء معلن في ``_migrate``.
ORG_SCHEMA_VERSION = 5


class OrgError(RuntimeError):
    """خطأ صريح في قواعد التنظيم — انتقال غير قانوني أو غياب سجل."""


class _LockedConnection:
    """غلاف اتصال SQLite بقفل واحد — نفس نمط الطبقة التشغيلية."""

    def __init__(self, conn: sqlite3.Connection, lock: threading.RLock) -> None:
        self._conn = conn
        self._lock = lock

    def execute(self, sql: str,
                params: tuple[Any, ...] | list[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def executescript(self, script: str) -> None:
        """تنفيذ مخطط متعدد العبارات داخل القفل والمعاملة."""
        with self._lock:
            self._conn.executescript(script)
            self._conn.commit()

    def __enter__(self) -> sqlite3.Connection:
        self._lock.acquire()
        return self._conn

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._lock.release()


class OrgStore:
    """المتجر الموحّد للتنظيم — واجهة واحدة لكل جداول الأقسام."""

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
        with self._lock:
            self._migrate()

    # ── المخطط والهجرة ────────────────────────────────────────────────────

    def _migrate(self) -> None:
        """بناء/ترقية المخطط — الرقم في ``meta`` هو المرجع الوحيد."""
        with self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS meta ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = 'org_schema_version'"
            ).fetchone()
            current = int(row["value"]) if row else 0
            if current < 1:
                self._create_v1()
                current = 1
            if current < 2:
                self._migrate_v2()
                current = 2
            if current < 3:
                self._migrate_v3()
                current = 3
            if current < 4:
                self._migrate_v4()
                current = 4
            if current < 5:
                self._migrate_v5()
                current = 5
            if current > ORG_SCHEMA_VERSION:
                raise OrgError(
                    f"مخطط متجر التنظيم أحدث من الكود: {current} > {ORG_SCHEMA_VERSION}")
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES ('org_schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(ORG_SCHEMA_VERSION),),
            )

    def _create_v1(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS missions (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, objective TEXT NOT NULL,
                repo_path TEXT, phase TEXT NOT NULL, status TEXT NOT NULL,
                acceptance_criteria TEXT, constraints TEXT, ambiguities TEXT,
                branch TEXT, patch_path TEXT, report_path TEXT, ticket_ids TEXT,
                revision_loops INTEGER, created_at TEXT, updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, dept TEXT NOT NULL,
                kind TEXT NOT NULL, description TEXT NOT NULL, deps TEXT,
                params TEXT, state TEXT NOT NULL, attempts INTEGER DEFAULT 0,
                result TEXT, error TEXT, updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS agent_runs (
                id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, task_id TEXT NOT NULL,
                role TEXT NOT NULL, provider TEXT, model TEXT, status TEXT,
                attempts INTEGER, tokens_in INTEGER, tokens_out INTEGER,
                cost_usd REAL, latency_ms REAL, log_ref TEXT, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, task_id TEXT NOT NULL,
                reviewer TEXT NOT NULL, lens TEXT NOT NULL, verdict TEXT NOT NULL,
                score INTEGER NOT NULL, comments TEXT, issues TEXT,
                debate_round INTEGER, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS findings (
                id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, source TEXT NOT NULL,
                category TEXT NOT NULL, severity TEXT NOT NULL, description TEXT,
                file TEXT, line INTEGER, evidence_ids TEXT, status TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS claims (
                id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, agent_role TEXT,
                statement TEXT, claim_kind TEXT, status TEXT, evidence_ids TEXT,
                resolution TEXT, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, kind TEXT NOT NULL,
                detail TEXT, captured_by TEXT, ok INTEGER, claim_id TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, kind TEXT NOT NULL,
                subject TEXT NOT NULL, note TEXT, approved INTEGER, decided_by TEXT,
                decided_at TEXT, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS lessons (
                id TEXT PRIMARY KEY, text TEXT NOT NULL, scope TEXT NOT NULL,
                confidence REAL, source_mission_id TEXT, applied_count INTEGER,
                active INTEGER, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS org_metrics (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, value REAL NOT NULL,
                tags TEXT, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
                actor TEXT NOT NULL, action TEXT NOT NULL, ref TEXT,
                details TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_mission ON tasks(mission_id);
            CREATE INDEX IF NOT EXISTS idx_reviews_mission ON reviews(mission_id);
            CREATE INDEX IF NOT EXISTS idx_findings_mission ON findings(mission_id);
            CREATE INDEX IF NOT EXISTS idx_claims_mission ON claims(mission_id);
            CREATE INDEX IF NOT EXISTS idx_evidence_mission ON evidence(mission_id);
            """
        )

    def _migrate_v2(self) -> None:
        """إضافة مطالبات تنفيذ ومحاولات دائمة دون إعادة تشغيل تلقائية."""
        columns = {row["name"] for row in self._conn.execute(
            "PRAGMA table_info(tasks)").fetchall()}
        additions = {
            "lease_owner": "TEXT NOT NULL DEFAULT ''",
            "lease_token": "TEXT NOT NULL DEFAULT ''",
            "lease_expires_at": "TEXT NOT NULL DEFAULT ''",
            "idempotency_key": "TEXT NOT NULL DEFAULT ''",
            "input_snapshot": "TEXT NOT NULL DEFAULT ''",
        }
        with self._conn:
            for name, definition in additions.items():
                if name not in columns:
                    self._conn.execute(
                        f"ALTER TABLE tasks ADD COLUMN {name} {definition}")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS task_attempts (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    attempt_no INTEGER NOT NULL,
                    worker_id TEXT NOT NULL,
                    lease_token TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    UNIQUE(task_id, attempt_no)
                )"""
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_attempts_task "
                "ON task_attempts(task_id, attempt_no)"
            )

    def _migrate_v3(self) -> None:
        """سجل قرارات المصالحة البشرية — منفصل عن الفحص والتنفيذ."""
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS task_reconciliations (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                mission_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                reason TEXT NOT NULL,
                evidence_refs TEXT NOT NULL DEFAULT '[]',
                decision_key TEXT NOT NULL,
                replacement_task_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(task_id, decision_key)
            );
            CREATE INDEX IF NOT EXISTS idx_task_reconciliations_mission
                ON task_reconciliations(mission_id, created_at);
            """
        )

    def _migrate_v4(self) -> None:
        """سجل لقطات سياق المهمة وبصمات المصدر ونسخة العمل."""
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS mission_context_snapshots (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                schema_version INTEGER NOT NULL,
                payload TEXT NOT NULL,
                payload_digest TEXT NOT NULL,
                repo_fingerprint TEXT NOT NULL,
                worktree_path TEXT NOT NULL DEFAULT '',
                worktree_fingerprint TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(mission_id, sequence)
            );
            CREATE INDEX IF NOT EXISTS idx_mission_context_snapshots_latest
                ON mission_context_snapshots(mission_id, sequence DESC);
            CREATE TRIGGER IF NOT EXISTS trg_mission_context_snapshots_no_update
                BEFORE UPDATE ON mission_context_snapshots
                BEGIN SELECT RAISE(ABORT, 'mission context snapshots are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS trg_mission_context_snapshots_no_delete
                BEFORE DELETE ON mission_context_snapshots
                BEGIN SELECT RAISE(ABORT, 'mission context snapshots are immutable'); END;
            """
        )

    def _migrate_v5(self) -> None:
        """قفل استئناف دائم بمستوى المهمة العليا — لا استيلاء تلقائي."""
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS mission_resume_runs (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                token TEXT NOT NULL UNIQUE,
                actor TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN
                    ('running', 'completed', 'failed', 'abandoned')),
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL DEFAULT '',
                finish_reason TEXT NOT NULL DEFAULT ''
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_mission_resume_one_active
                ON mission_resume_runs(mission_id) WHERE status = 'running';
            CREATE INDEX IF NOT EXISTS idx_mission_resume_history
                ON mission_resume_runs(mission_id, started_at, id);
            """
        )

    def claim_mission_resume(
            self, mission_id: str, *, actor: str, reason: str) -> dict[str, Any]:
        """امتلاك حصري ذري لاستئناف mission؛ السجل العالق يحجب التنفيذ."""
        actor = actor.strip() if isinstance(actor, str) else ""
        reason = reason.strip() if isinstance(reason, str) else ""
        if not mission_id.strip() or not actor or not reason:
            raise OrgError("mission_id وهوية المشغّل وسبب الاستئناف مطلوبة")
        token = secrets.token_urlsafe(32)
        run_id = new_id("org-resume", mission_id, token)
        now = self._now()
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            if self._conn.execute(
                    "SELECT 1 FROM missions WHERE id=?", (mission_id,)
            ).fetchone() is None:
                raise OrgError(f"مهمة غير موجودة: {mission_id}")
            active = self._conn.execute(
                "SELECT id FROM mission_resume_runs "
                "WHERE mission_id=? AND status='running'", (mission_id,)
            ).fetchone()
            if active is not None:
                raise OrgError(
                    "استئناف المهمة محجوب: توجد جلسة استئناف نشطة أو متروكة "
                    "تتطلب مصالحة بشرية")
            self._conn.execute(
                "INSERT INTO mission_resume_runs "
                "(id, mission_id, token, actor, reason, status, started_at) "
                "VALUES (?, ?, ?, ?, ?, 'running', ?)",
                (run_id, mission_id, token, actor, reason, now),
            )
            self._conn.execute(
                "INSERT INTO audit (ts, actor, action, ref, details) "
                "VALUES (?, ?, 'mission.resume_claimed', ?, ?)",
                (now, actor, mission_id, json.dumps(
                    {"run_id": run_id, "reason": reason},
                    sort_keys=True, ensure_ascii=False)),
            )
        return {"id": run_id, "mission_id": mission_id, "token": token,
                "actor": actor, "reason": reason, "status": "running",
                "started_at": now}

    def finish_mission_resume(
            self, mission_id: str, token: str, *,
            status: str, reason: str = "") -> None:
        """إنهاء جلسة يملكها الرمز المطابق فقط."""
        if status not in {"completed", "failed"}:
            raise OrgError("حالة إنهاء جلسة الاستئناف غير صالحة")
        now = self._now()
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT id, actor FROM mission_resume_runs "
                "WHERE mission_id=? AND token=? AND status='running'",
                (mission_id, token),
            ).fetchone()
            if row is None:
                raise OrgError("رمز جلسة الاستئناف قديم أو لا يملك الجلسة")
            self._conn.execute(
                "UPDATE mission_resume_runs SET status=?, finished_at=?, "
                "finish_reason=? WHERE id=? AND token=? AND status='running'",
                (status, now, reason, row["id"], token),
            )
            self._conn.execute(
                "INSERT INTO audit (ts, actor, action, ref, details) "
                "VALUES (?, ?, 'mission.resume_finished', ?, ?)",
                (now, row["actor"], mission_id, json.dumps(
                    {"run_id": row["id"], "status": status, "reason": reason},
                    sort_keys=True, ensure_ascii=False)),
            )

    def abandon_mission_resume(
            self, mission_id: str, *, actor: str, reason: str,
            confirm_process_stopped: bool) -> None:
        """رفع قفل يتيم بقرار بشري صريح بعد تأكيد توقف العملية القديمة."""
        actor = actor.strip() if isinstance(actor, str) else ""
        reason = reason.strip() if isinstance(reason, str) else ""
        if not actor or not reason or confirm_process_stopped is not True:
            raise OrgError(
                "يتطلب تحرير القفل هوية وسببًا وتأكيد توقف العملية القديمة")
        now = self._now()
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT id FROM mission_resume_runs "
                "WHERE mission_id=? AND status='running'", (mission_id,)
            ).fetchone()
            if row is None:
                raise OrgError("لا توجد جلسة استئناف نشطة لمصالحتها")
            self._conn.execute(
                "UPDATE mission_resume_runs SET status='abandoned', "
                "finished_at=?, finish_reason=? WHERE id=? AND status='running'",
                (now, reason, row["id"]),
            )
            self._conn.execute(
                "INSERT INTO audit (ts, actor, action, ref, details) "
                "VALUES (?, ?, 'mission.resume_abandoned', ?, ?)",
                (now, actor, mission_id, json.dumps(
                    {"run_id": row["id"], "reason": reason,
                     "process_stopped_confirmed": True},
                    sort_keys=True, ensure_ascii=False)),
            )

    def mission_resume_runs_for(self, mission_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, mission_id, actor, reason, status, started_at, "
            "finished_at, finish_reason FROM mission_resume_runs "
            "WHERE mission_id=? ORDER BY started_at, id", (mission_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    # ── التدقيق ───────────────────────────────────────────────────────────

    def audit(self, action: str, ref: str = "",
              details: dict[str, Any] | None = None,
              actor: str = "org") -> None:
        """سطر تدقيق واحد غير محذوف — كل قرار حسّاس يمر هنا."""
        from src.ops.contracts import now_iso
        with self._conn:
            self._conn.execute(
                "INSERT INTO audit (ts, actor, action, ref, details) "
                "VALUES (?, ?, ?, ?, ?)",
                (now_iso(), actor, action, ref,
                 json.dumps(details or {}, sort_keys=True, ensure_ascii=False)),
            )

    def tail_audit(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        out = []
        for r in rows:
            out.append({
                "ts": r["ts"], "actor": r["actor"], "action": r["action"],
                "ref": r["ref"] or "", "details": json.loads(r["details"] or "{}"),
            })
        return out

    def save_mission_context_snapshot(
            self, mission_id: str, payload: dict[str, Any],
            repo_fingerprint: dict[str, Any], worktree_path: str = "",
            worktree_fingerprint: str = "", schema_version: int = 1) -> dict[str, Any]:
        """Append an immutable context checkpoint; source baseline cannot drift."""
        if not mission_id.strip() or not isinstance(payload, dict):
            raise OrgError("mission_id وpayload صالحان مطلوبان")
        if not isinstance(repo_fingerprint, dict) or not repo_fingerprint.get("digest"):
            raise OrgError("بصمة المستودع غير صالحة")
        if bool(worktree_path) != bool(worktree_fingerprint):
            raise OrgError("مسار نسخة العمل وبصمتها يجب أن يظهرا معًا")
        if not payload.get("task_ledger_digest"):
            raise OrgError("بصمة سجل المهام مطلوبة داخل checkpoint")
        encoded_payload = json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        payload_digest = hashlib.sha256(encoded_payload.encode("utf-8")).hexdigest()
        encoded_repo = json.dumps(
            repo_fingerprint, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        now = self._now()
        snapshot_id = new_id("org-ctx", mission_id, now, encoded_payload)
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            mission = self._conn.execute(
                "SELECT id FROM missions WHERE id = ?", (mission_id,)
            ).fetchone()
            if mission is None:
                raise OrgError(f"مهمة غير موجودة: {mission_id}")
            ledger_rows = self._conn.execute(
                "SELECT id, mission_id, dept, kind, description, deps, params, "
                "state, attempts, result, error, updated_at, idempotency_key, "
                "input_snapshot FROM tasks WHERE mission_id = ? ORDER BY id",
                (mission_id,),
            ).fetchall()
            ledger = [dict(row) for row in ledger_rows]
            encoded_ledger = json.dumps(
                ledger, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            current_ledger_digest = hashlib.sha256(
                encoded_ledger.encode("utf-8")).hexdigest()
            if payload["task_ledger_digest"] != current_ledger_digest:
                raise OrgError(
                    "سجل المهام تغيّر أثناء checkpoint؛ اللقطة لم تُحفظ")
            latest = self._conn.execute(
                "SELECT sequence, repo_fingerprint FROM mission_context_snapshots "
                "WHERE mission_id = ? ORDER BY sequence DESC LIMIT 1",
                (mission_id,),
            ).fetchone()
            if latest is not None and latest["repo_fingerprint"] != encoded_repo:
                raise OrgError(
                    "بصمة المستودع تغيّرت منذ أول checkpoint؛ الاستئناف يتطلب مراجعة بشرية")
            sequence = int(latest["sequence"]) + 1 if latest else 1
            self._conn.execute(
                "INSERT INTO mission_context_snapshots "
                "(id, mission_id, sequence, schema_version, payload, payload_digest, "
                "repo_fingerprint, worktree_path, worktree_fingerprint, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (snapshot_id, mission_id, sequence, schema_version, encoded_payload,
                 payload_digest, encoded_repo, worktree_path, worktree_fingerprint, now),
            )
        self.audit("mission.context_checkpoint", mission_id, {
            "snapshot_id": snapshot_id, "sequence": sequence,
            "repo_digest": repo_fingerprint["digest"],
            "worktree_fingerprint": worktree_fingerprint,
        })
        return self.mission_context_snapshot_get(mission_id) or {}

    def mission_context_snapshot_get(
            self, mission_id: str, snapshot_id: str = "") -> dict[str, Any] | None:
        """Read the latest checkpoint, or one immutable checkpoint by ID."""
        if snapshot_id:
            row = self._conn.execute(
                "SELECT * FROM mission_context_snapshots "
                "WHERE mission_id = ? AND id = ?", (mission_id, snapshot_id)
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM mission_context_snapshots WHERE mission_id = ? "
                "ORDER BY sequence DESC LIMIT 1", (mission_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        actual_digest = hashlib.sha256(result["payload"].encode("utf-8")).hexdigest()
        if actual_digest != result["payload_digest"]:
            raise OrgError("بصمة محتوى checkpoint غير مطابقة؛ اللقطة مرفوضة")
        result["payload"] = json.loads(result["payload"])
        result["repo_fingerprint"] = json.loads(result["repo_fingerprint"])
        return result

    def mission_context_snapshots_for(self, mission_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM mission_context_snapshots WHERE mission_id = ? "
            "ORDER BY sequence", (mission_id,)
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            actual_digest = hashlib.sha256(item["payload"].encode("utf-8")).hexdigest()
            if actual_digest != item["payload_digest"]:
                raise OrgError("بصمة محتوى checkpoint غير مطابقة؛ اللقطة مرفوضة")
            item["payload"] = json.loads(item["payload"])
            item["repo_fingerprint"] = json.loads(item["repo_fingerprint"])
            result.append(item)
        return result

    # ── المهام العليا ─────────────────────────────────────────────────────

    def create_mission(self, mission: Mission) -> Mission:
        """تخزين مهمة بمعرّف حتمي — الإدخال المكرر يعيد الموجودة دون تعديل."""
        if not mission.id:
            mission = Mission(
                title=mission.title, objective=mission.objective,
                repo_path=mission.repo_path,
                acceptance_criteria=mission.acceptance_criteria,
                constraints=mission.constraints, ambiguities=mission.ambiguities,
                phase=mission.phase, status=mission.status,
                id=new_id("org-m", mission.title.strip(), mission.objective.strip()),
            )
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO missions (id, title, objective, repo_path, "
                "phase, status, acceptance_criteria, constraints, ambiguities, "
                "branch, patch_path, report_path, ticket_ids, revision_loops, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "?, ?, ?, ?, ?, ?)",
                (
                    mission.id, mission.title, mission.objective, mission.repo_path,
                    mission.phase, mission.status,
                    json.dumps(mission.acceptance_criteria, ensure_ascii=False),
                    json.dumps(mission.constraints, ensure_ascii=False),
                    json.dumps(mission.ambiguities, ensure_ascii=False),
                    mission.branch, mission.patch_path, mission.report_path,
                    json.dumps(mission.ticket_ids, ensure_ascii=False),
                    mission.revision_loops, mission.created_at, mission.updated_at,
                ),
            )
        stored = self.mission_get(mission.id)
        assert stored is not None
        self.audit("mission.created", mission.id, {"phase": stored.phase})
        return stored

    def _row_to_mission(self, r: sqlite3.Row) -> Mission:
        return Mission(
            title=r["title"], objective=r["objective"],
            repo_path=r["repo_path"] or "",
            acceptance_criteria=json.loads(r["acceptance_criteria"] or "[]"),
            constraints=json.loads(r["constraints"] or "[]"),
            ambiguities=json.loads(r["ambiguities"] or "[]"),
            phase=r["phase"], status=r["status"], branch=r["branch"] or "",
            patch_path=r["patch_path"] or "", report_path=r["report_path"] or "",
            ticket_ids=json.loads(r["ticket_ids"] or "[]"),
            revision_loops=int(r["revision_loops"] or 0),
            id=r["id"], created_at=r["created_at"], updated_at=r["updated_at"],
        )

    def mission_get(self, mission_id: str) -> Mission | None:
        row = self._conn.execute(
            "SELECT * FROM missions WHERE id = ?", (mission_id,)).fetchone()
        return self._row_to_mission(row) if row else None

    def mission_list(self, status: str | None = None) -> list[Mission]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM missions WHERE status = ? ORDER BY created_at",
                (status,)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM missions ORDER BY created_at").fetchall()
        return [self._row_to_mission(r) for r in rows]

    def mission_update(self, mission: Mission) -> Mission:
        """تحديث كامل لمهمة موجودة مع فرض انتقال الطور."""
        old = self.mission_get(mission.id)
        if old is None:
            raise OrgError(f"مهمة غير موجودة: {mission.id}")
        if mission.phase != old.phase:
            allowed = ALLOWED_PHASE_TRANSITIONS.get(old.phase, frozenset())
            if mission.phase not in allowed:
                raise OrgError(
                    f"انتقال طور غير قانوني: {old.phase} → {mission.phase} "
                    f"(المسموح: {sorted(allowed)})")
        with self._conn:
            self._conn.execute(
                "UPDATE missions SET phase = ?, status = ?, repo_path = ?, "
                "acceptance_criteria = ?, "
                "constraints = ?, ambiguities = ?, branch = ?, patch_path = ?, "
                "report_path = ?, ticket_ids = ?, revision_loops = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    mission.phase, mission.status, mission.repo_path,
                    json.dumps(mission.acceptance_criteria, ensure_ascii=False),
                    json.dumps(mission.constraints, ensure_ascii=False),
                    json.dumps(mission.ambiguities, ensure_ascii=False),
                    mission.branch, mission.patch_path, mission.report_path,
                    json.dumps(mission.ticket_ids, ensure_ascii=False),
                    mission.revision_loops, mission.updated_at, mission.id,
                ),
            )
        if mission.phase != old.phase:
            self.audit("mission.phase", mission.id,
                       {"from": old.phase, "to": mission.phase})
        if mission.status != old.status:
            self.audit("mission.status", mission.id,
                       {"from": old.status, "to": mission.status})
        stored = self.mission_get(mission.id)
        assert stored is not None
        return stored

    # ── مهام الرسم ────────────────────────────────────────────────────────

    def add_task(self, spec: TaskSpec) -> TaskSpec:
        """تخزين مهمة فرعية بمعرّف حتمي من محتواها."""
        if not spec.id:
            spec = spec.with_id(new_id(
                "org-t", spec.mission_id, spec.dept, spec.kind, spec.description))
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO tasks (id, mission_id, dept, kind, "
                "description, deps, params, state, attempts, result, error, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, '', '', ?)",
                (
                    spec.id, spec.mission_id, spec.dept, spec.kind,
                    spec.description,
                    json.dumps(spec.deps, ensure_ascii=False),
                    json.dumps(spec.params, sort_keys=True, ensure_ascii=False),
                    self._now(),
                ),
            )
        return spec

    def task_get(self, task_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def tasks_for_mission(self, mission_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE mission_id = ? ORDER BY id",
            (mission_id,)).fetchall()
        return [dict(r) for r in rows]

    def task_set_state(self, task_id: str, state: str,
                       result: dict[str, Any] | None = None,
                       error: str = "", attempts: int = 0) -> None:
        """تغيير حالة مهمة فرعية مع سطر تدقيق — الحالة من المعلن أو رفع."""
        from src.org.contracts import TASK_STATES
        if state not in TASK_STATES:
            raise OrgError(f"حالة مهمة غير معلنة: {state}")
        with self._conn:
            self._conn.execute(
                "UPDATE tasks SET state = ?, result = ?, error = ?, "
                "attempts = MAX(attempts, ?), updated_at = ? WHERE id = ?",
                (
                    state,
                    json.dumps(result or {}, sort_keys=True, ensure_ascii=False),
                    error, attempts, self._now(), task_id,
                ),
            )
        self.audit("task.state", task_id, {"to": state, "error": error[:200]})

    def claim_task(self, task_id: str, worker_id: str,
                   lease_seconds: int = 300) -> dict[str, Any] | None:
        """مطالبة ذرية بمهمة pending؛ لا تستولي على running أو lease منتهية."""
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise OrgError("worker_id مطلوب")
        if not isinstance(lease_seconds, int) or lease_seconds < 1:
            raise OrgError("lease_seconds يجب أن يكون عددًا موجبًا")
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        started_at = now.isoformat()
        expires_at = (now + timedelta(seconds=lease_seconds)).isoformat()
        with self._conn:
            row = self._conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise OrgError(f"مهمة فرعية غير موجودة: {task_id}")
            if row["state"] != "pending":
                return None
            snapshot = row["input_snapshot"] or json.dumps({
                "mission_id": row["mission_id"], "dept": row["dept"],
                "kind": row["kind"], "description": row["description"],
                "deps": json.loads(row["deps"] or "[]"),
                "params": json.loads(row["params"] or "{}"),
            }, sort_keys=True, ensure_ascii=False)
            idem = row["idempotency_key"] or new_id(
                "org-idem", row["mission_id"], row["id"])
            updated = self._conn.execute(
                """UPDATE tasks SET state='running', attempts=attempts+1,
                   lease_owner=?, lease_token=?, lease_expires_at=?,
                   idempotency_key=?, input_snapshot=?, updated_at=?
                   WHERE id=? AND state='pending'""",
                (worker_id.strip(), token, expires_at, idem, snapshot,
                 started_at, task_id),
            )
            if updated.rowcount != 1:
                return None
            attempt_no = int(row["attempts"] or 0) + 1
            attempt_id = new_id("org-attempt", task_id, str(attempt_no), token)
            self._conn.execute(
                """INSERT INTO task_attempts
                   (id, task_id, attempt_no, worker_id, lease_token,
                    status, started_at)
                   VALUES (?, ?, ?, ?, ?, 'running', ?)""",
                (attempt_id, task_id, attempt_no, worker_id.strip(), token,
                 started_at),
            )
            self._conn.execute(
                "INSERT INTO audit (ts, actor, action, ref, details) "
                "VALUES (?, ?, 'task.claimed', ?, ?)",
                (started_at, worker_id.strip(), task_id,
                 json.dumps({"attempt": attempt_no, "lease_expires_at": expires_at},
                            sort_keys=True)),
            )
            claimed = self._conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return dict(claimed) if claimed else None

    def finish_claimed_task(self, task_id: str, lease_token: str,
                            result: dict[str, Any]) -> None:
        """إنهاء مطالبة صحيحة فقط؛ token قديم أو غير مالك مرفوض."""
        self._finish_claimed_task(task_id, lease_token, "done", result, "")

    def fail_claimed_task(self, task_id: str, lease_token: str,
                          error: str) -> None:
        """تسجيل فشل مطالبة صحيحة فقط دون إعادة محاولة تلقائية."""
        self._finish_claimed_task(task_id, lease_token, "failed", {}, error)

    def _finish_claimed_task(self, task_id: str, lease_token: str,
                             state: str, result: dict[str, Any],
                             error: str) -> None:
        if not lease_token:
            raise OrgError("lease_token مطلوب")
        now = self._now()
        with self._conn:
            row = self._conn.execute(
                "SELECT lease_token, state FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if row is None or row["state"] != "running" or not secrets.compare_digest(
                str(row["lease_token"]), lease_token
            ):
                raise OrgError("مطالبة المهمة غير صالحة أو لم تعد مملوكة للعامل")
            self._conn.execute(
                """UPDATE tasks SET state=?, result=?, error=?,
                   lease_owner='', lease_token='', lease_expires_at='',
                   updated_at=? WHERE id=? AND state='running' AND lease_token=?""",
                (state, json.dumps(result, sort_keys=True, ensure_ascii=False),
                 error, now, task_id, lease_token),
            )
            self._conn.execute(
                """UPDATE task_attempts SET status=?, finished_at=?, error=?
                   WHERE task_id=? AND lease_token=? AND status='running'""",
                (state, now, error, task_id, lease_token),
            )
            self._conn.execute(
                "INSERT INTO audit (ts, actor, action, ref, details) "
                "VALUES (?, 'org', ?, ?, ?)",
                (now, f"task.{state}", task_id,
                 json.dumps({"error": error[:200]}, sort_keys=True)),
            )

    def task_attempts_for(self, task_id: str) -> list[dict[str, Any]]:
        """سجل المحاولات بالترتيب؛ لا يُستبدل بتاريخ المهمة الحالي."""
        rows = self._conn.execute(
            "SELECT * FROM task_attempts WHERE task_id=? ORDER BY attempt_no",
            (task_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def reconcile_task(
        self, task_id: str, action: str, actor: str, reason: str,
        decision_key: str, evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        """تطبيق قرار مشغّل صريح؛ لا يشغّل المهمة ولا يستولي على lease."""
        allowed = {"manual_hold", "mark_failed", "mark_completed_with_evidence",
                   "retry_authorized"}
        if action not in allowed:
            raise OrgError(f"قرار مصالحة غير معروف: {action}")
        if not all(isinstance(v, str) and v.strip()
                   for v in (actor, reason, decision_key)):
            raise OrgError("actor وreason وdecision_key مطلوبة")
        refs = list(evidence_refs or [])
        if any(not isinstance(ref, str) or not ref.strip() for ref in refs):
            raise OrgError("مراجع الأدلة يجب أن تكون نصوصًا غير فارغة")
        if len(refs) != len(set(refs)):
            raise OrgError("مراجع الأدلة المكررة مرفوضة")
        now = self._now()
        with self._conn:
            # Serialize decisions across separate SQLite connections.
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise OrgError(f"مهمة فرعية غير موجودة: {task_id}")
            existing = self._conn.execute(
                "SELECT * FROM task_reconciliations WHERE task_id=? AND decision_key=?",
                (task_id, decision_key),
            ).fetchone()
            if existing:
                stored_refs = json.loads(existing["evidence_refs"] or "[]")
                if (existing["action"] != action
                        or existing["actor"] != actor.strip()
                        or existing["reason"] != reason.strip()
                        or stored_refs != refs):
                    raise OrgError("decision_key مستخدم لبيانات قرار مختلفة")
                return dict(existing)
            if action != "manual_hold":
                prior_terminal = self._conn.execute(
                    """SELECT id FROM task_reconciliations
                       WHERE task_id=? AND action IN
                       ('mark_failed','mark_completed_with_evidence','retry_authorized')
                       LIMIT 1""", (task_id,)
                ).fetchone()
                if prior_terminal:
                    raise OrgError("سبق حسم المهمة بقرار نهائي")
            state = str(row["state"])
            if state not in {"running", "failed"}:
                raise OrgError(f"لا يمكن مصالحة مهمة بحالة {state}")
            if action in {"mark_failed", "mark_completed_with_evidence",
                          "retry_authorized"} and state == "running":
                expiry = str(row["lease_expires_at"] or "")
                try:
                    expires_at = datetime.fromisoformat(expiry) if expiry else None
                    if expires_at is not None and expires_at.tzinfo is None:
                        raise ValueError("lease expiry must be timezone-aware")
                    expired = (expires_at is not None
                               and expires_at.astimezone(timezone.utc)
                               <= datetime.now(timezone.utc))
                except (TypeError, ValueError):
                    expired = False
                if not expired:
                    raise OrgError("لا يمكن حسم مطالبة running قبل انتهاء lease")
            if action == "mark_completed_with_evidence":
                if not refs:
                    raise OrgError("إكمال المهمة يتطلب مراجع الأدلة")
                placeholders = ",".join("?" for _ in refs)
                evidence_rows = self._conn.execute(
                    f"SELECT id FROM evidence WHERE mission_id=? AND ok=1 AND id IN ({placeholders})",
                    (row["mission_id"], *refs),
                ).fetchall()
                if len({r["id"] for r in evidence_rows}) != len(set(refs)):
                    raise OrgError("كل مراجع الأدلة يجب أن تشير إلى أدلة ناجحة للمهمة نفسها")
            decision_id = new_id("org-reconcile", task_id, decision_key)
            replacement_id = ""
            if action == "retry_authorized":
                params = json.loads(row["params"] or "{}")
                params["operator_retry_of"] = task_id
                params["operator_decision_id"] = decision_id
                deps = json.loads(row["deps"] or "[]")
                replacement_id = new_id(
                    "org-t", row["mission_id"], row["dept"], row["kind"],
                    f"{row['description']} [operator retry {decision_id}]")
                params["retry_sequence"] = int(params.get("retry_sequence", 0)) + 1
                self._conn.execute(
                    """INSERT INTO tasks
                    (id, mission_id, dept, kind, description, deps, params,
                     state, attempts, result, error, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, '', '', ?)""",
                    (replacement_id, row["mission_id"], row["dept"], row["kind"],
                     f"{row['description']} [operator-authorized retry]",
                     json.dumps(deps, ensure_ascii=False),
                     json.dumps(params, sort_keys=True, ensure_ascii=False), now),
                )
            if action in {"mark_failed", "mark_completed_with_evidence",
                          "retry_authorized"}:
                target = "done" if action == "mark_completed_with_evidence" else "failed"
                result = (json.dumps({"operator_reconciled": True,
                                      "evidence_refs": refs},
                                     sort_keys=True, ensure_ascii=False)
                          if target == "done" else row["result"])
                self._conn.execute(
                    """UPDATE tasks SET state=?, result=?, error=?,
                       lease_owner='', lease_token='', lease_expires_at=?,
                       updated_at=? WHERE id=? AND state=?""",
                    (target, result,
                     "" if target == "done" else (row["error"] or "operator marked failed"),
                     "", now, task_id, state),
                )
                if state == "running":
                    self._conn.execute(
                        """UPDATE task_attempts SET status=?, finished_at=?, error=?
                           WHERE task_id=? AND status='running'""",
                        ("done" if target == "done" else "failed", now,
                         "" if target == "done" else "operator reconciliation",
                         task_id),
                    )
            self._conn.execute(
                """INSERT INTO task_reconciliations
                   (id, task_id, mission_id, action, actor, reason,
                    evidence_refs, decision_key, replacement_task_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (decision_id, task_id, row["mission_id"], action, actor.strip(),
                 reason.strip(), json.dumps(refs, ensure_ascii=False),
                 decision_key, replacement_id, now),
            )
            self._conn.execute(
                """INSERT INTO audit (ts, actor, action, ref, details)
                   VALUES (?, ?, 'task.reconciled', ?, ?)""",
                (now, actor.strip(), task_id, json.dumps({
                    "action": action, "reason": reason.strip(),
                    "decision_id": decision_id, "evidence_refs": refs,
                    "replacement_task_id": replacement_id,
                }, sort_keys=True, ensure_ascii=False)),
            )
            decision = self._conn.execute(
                "SELECT * FROM task_reconciliations WHERE id=?", (decision_id,)
            ).fetchone()
        return dict(decision) if decision else {}

    def task_reconciliations_for(self, mission_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM task_reconciliations WHERE mission_id=? ORDER BY created_at, id",
            (mission_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    # ── تشغيلات الوكلاء ───────────────────────────────────────────────────

    def add_agent_run(self, mission_id: str, task_id: str, role: str,
                      provider: str, model: str, status: str, attempts: int,
                      tokens_in: int, tokens_out: int, cost_usd: float,
                      latency_ms: float, log_ref: str = "") -> str:
        run_id = new_id("org-r", mission_id, task_id, role,
                        str(tokens_in), str(tokens_out))
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO agent_runs (id, mission_id, task_id, role, "
                "provider, model, status, attempts, tokens_in, tokens_out, "
                "cost_usd, latency_ms, log_ref, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, mission_id, task_id, role, provider, model, status,
                 attempts, tokens_in, tokens_out, cost_usd, latency_ms,
                 log_ref, self._now()),
            )
        return run_id

    def agent_runs_for(self, mission_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM agent_runs WHERE mission_id = ? ORDER BY created_at",
            (mission_id,)).fetchall()
        return [dict(r) for r in rows]

    # ── المراجعات ─────────────────────────────────────────────────────────

    def add_review(self, review: Review) -> Review:
        if not review.id:
            review = Review(
                mission_id=review.mission_id, task_id=review.task_id,
                reviewer=review.reviewer, lens=review.lens,
                verdict=review.verdict, score=review.score,
                comments=review.comments, issues=review.issues,
                debate_round=review.debate_round,
                id=new_id("org-rv", review.mission_id, review.task_id,
                          review.reviewer, review.lens, str(review.debate_round)),
            )
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO reviews (id, mission_id, task_id, reviewer, "
                "lens, verdict, score, comments, issues, debate_round, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    review.id, review.mission_id, review.task_id, review.reviewer,
                    review.lens, review.verdict, review.score, review.comments,
                    json.dumps(review.issues, ensure_ascii=False),
                    review.debate_round, self._now(),
                ),
            )
        return review

    def reviews_for(self, mission_id: str, task_id: str | None = None,
                    debate_round: int | None = None) -> list[Review]:
        sql = "SELECT * FROM reviews WHERE mission_id = ?"
        params: list[Any] = [mission_id]
        if task_id:
            sql += " AND task_id = ?"
            params.append(task_id)
        if debate_round is not None:
            sql += " AND debate_round = ?"
            params.append(debate_round)
        sql += " ORDER BY id"
        rows = self._conn.execute(sql, params).fetchall()
        return [
            Review(
                mission_id=r["mission_id"], task_id=r["task_id"],
                reviewer=r["reviewer"], lens=r["lens"], verdict=r["verdict"],
                score=int(r["score"]), comments=r["comments"] or "",
                issues=json.loads(r["issues"] or "[]"),
                debate_round=int(r["debate_round"] or 0), id=r["id"],
            )
            for r in rows
        ]

    # ── نتائج الفحص ───────────────────────────────────────────────────────

    def add_finding(self, finding: Finding) -> Finding:
        if not finding.id:
            finding = Finding(
                mission_id=finding.mission_id, source=finding.source,
                category=finding.category, severity=finding.severity,
                description=finding.description, file=finding.file,
                line=finding.line, evidence_ids=finding.evidence_ids,
                status=finding.status,
                id=new_id("org-f", finding.mission_id, finding.source,
                          finding.category, finding.description,
                          finding.file, str(finding.line)),
            )
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO findings (id, mission_id, source, category, "
                "severity, description, file, line, evidence_ids, status, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    finding.id, finding.mission_id, finding.source,
                    finding.category, finding.severity, finding.description,
                    finding.file, finding.line,
                    json.dumps(finding.evidence_ids, ensure_ascii=False),
                    finding.status, self._now(),
                ),
            )
        return finding

    def findings_for(self, mission_id: str,
                     status: str | None = None) -> list[Finding]:
        sql = "SELECT * FROM findings WHERE mission_id = ?"
        params: list[Any] = [mission_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY id"
        rows = self._conn.execute(sql, params).fetchall()
        return [
            Finding(
                mission_id=r["mission_id"], source=r["source"],
                category=r["category"], severity=r["severity"],
                description=r["description"], file=r["file"] or "",
                line=int(r["line"] or 0),
                evidence_ids=json.loads(r["evidence_ids"] or "[]"),
                status=r["status"], id=r["id"],
            )
            for r in rows
        ]

    def finding_set_status(self, finding_id: str, status: str) -> None:
        if status not in ("open", "fixed", "wontfix"):
            raise OrgError(f"حالة نتيجة غير معلنة: {status}")
        with self._conn:
            self._conn.execute(
                "UPDATE findings SET status = ? WHERE id = ?", (status, finding_id))
        self.audit("finding.status", finding_id, {"to": status})

    # ── الادعاءات والأدلة ─────────────────────────────────────────────────

    def add_claim(self, claim: Claim) -> Claim:
        if not claim.id:
            claim = Claim(
                mission_id=claim.mission_id, agent_role=claim.agent_role,
                statement=claim.statement, claim_kind=claim.claim_kind,
                status=claim.status, evidence_ids=claim.evidence_ids,
                resolution=claim.resolution,
                id=new_id("org-c", claim.mission_id, claim.agent_role,
                          claim.statement),
            )
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO claims (id, mission_id, agent_role, "
                "statement, claim_kind, status, evidence_ids, resolution, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    claim.id, claim.mission_id, claim.agent_role,
                    claim.statement, claim.claim_kind, claim.status,
                    json.dumps(claim.evidence_ids, ensure_ascii=False),
                    claim.resolution, self._now(),
                ),
            )
        return claim

    def claim_get(self, claim_id: str) -> Claim | None:
        row = self._conn.execute(
            "SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
        if not row:
            return None
        return Claim(
            mission_id=row["mission_id"], agent_role=row["agent_role"],
            statement=row["statement"], claim_kind=row["claim_kind"] or "observation",
            status=row["status"], evidence_ids=json.loads(row["evidence_ids"] or "[]"),
            resolution=row["resolution"] or "", id=row["id"],
        )

    def claim_resolve(self, claim_id: str, status: str,
                      resolution: str, evidence_ids: list[str]) -> Claim:
        """حسم ادعاء بالأدلة — «محقَّق» بلا أدلة رفع صريح."""
        claim = self.claim_get(claim_id)
        if claim is None:
            raise OrgError(f"ادعاء غير موجود: {claim_id}")
        if status == "verified" and not evidence_ids:
            raise OrgError("حسم ادعاء كـ«محقَّق» بلا أدلة مرفوض")
        resolved = Claim(
            mission_id=claim.mission_id, agent_role=claim.agent_role,
            statement=claim.statement, claim_kind=claim.claim_kind,
            status=status, evidence_ids=evidence_ids, resolution=resolution,
            id=claim.id,
        )
        with self._conn:
            self._conn.execute(
                "UPDATE claims SET status = ?, evidence_ids = ?, resolution = ? "
                "WHERE id = ?",
                (
                    status, json.dumps(evidence_ids, ensure_ascii=False),
                    resolution, claim_id,
                ),
            )
        self.audit("claim.resolved", claim_id, {"to": status})
        return resolved

    def claims_for(self, mission_id: str) -> list[Claim]:
        rows = self._conn.execute(
            "SELECT * FROM claims WHERE mission_id = ? ORDER BY id",
            (mission_id,)).fetchall()
        return [
            Claim(
                mission_id=r["mission_id"], agent_role=r["agent_role"],
                statement=r["statement"], claim_kind=r["claim_kind"] or "observation",
                status=r["status"], evidence_ids=json.loads(r["evidence_ids"] or "[]"),
                resolution=r["resolution"] or "", id=r["id"],
            )
            for r in rows
        ]

    def add_evidence(self, evidence: Evidence) -> Evidence:
        if not evidence.id:
            # المعرّف يشمل claim_id — دليلان بنفس التفصيل لادعاءين مختلفين
            # لا يتصادمان، والدليل مرتبط بادعائه حتميًا.
            evidence = Evidence(
                mission_id=evidence.mission_id, kind=evidence.kind,
                detail=evidence.detail, captured_by=evidence.captured_by,
                ok=evidence.ok, claim_id=evidence.claim_id,
                id=new_id("org-e", evidence.mission_id, evidence.kind,
                          json.dumps(evidence.detail, sort_keys=True,
                                     ensure_ascii=False),
                          evidence.captured_by, evidence.claim_id),
            )
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO evidence (id, mission_id, kind, detail, "
                "captured_by, ok, claim_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    evidence.id, evidence.mission_id, evidence.kind,
                    json.dumps(evidence.detail, sort_keys=True, ensure_ascii=False),
                    evidence.captured_by, int(evidence.ok), evidence.claim_id,
                    self._now(),
                ),
            )
        return evidence

    def evidence_for(self, mission_id: str, claim_id: str | None = None) -> list[Evidence]:
        sql = "SELECT * FROM evidence WHERE mission_id = ?"
        params: list[Any] = [mission_id]
        if claim_id:
            sql += " AND claim_id = ?"
            params.append(claim_id)
        sql += " ORDER BY id"
        rows = self._conn.execute(sql, params).fetchall()
        return [
            Evidence(
                mission_id=r["mission_id"], kind=r["kind"],
                detail=json.loads(r["detail"] or "{}"),
                captured_by=r["captured_by"] or "",
                ok=bool(r["ok"]), claim_id=r["claim_id"] or "", id=r["id"],
            )
            for r in rows
        ]

    # ── الموافقات البشرية ─────────────────────────────────────────────────

    def request_approval(self, approval: Approval) -> Approval:
        if not approval.id:
            approval = Approval(
                mission_id=approval.mission_id, kind=approval.kind,
                subject=approval.subject, note=approval.note,
                id=new_id("org-a", approval.mission_id, approval.kind,
                          approval.subject),
            )
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO approvals (id, mission_id, kind, subject, "
                "note, approved, decided_by, decided_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    approval.id, approval.mission_id, approval.kind,
                    approval.subject, approval.note,
                    None if approval.approved is None else int(approval.approved),
                    approval.decided_by, approval.decided_at, self._now(),
                ),
            )
        self.audit("approval.requested", approval.id,
                   {"kind": approval.kind, "subject": approval.subject})
        return approval

    def decide_approval(self, approval_id: str, approved: bool,
                        decided_by: str) -> Approval:
        """تسجيل قرار بشري — قرار بلا اسم صانع مرفوض."""
        if not decided_by.strip():
            raise OrgError("قرار الموافقة يحتاج اسم صانع القرار")
        row = self._conn.execute(
            "SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if not row:
            raise OrgError(f"طلب موافقة غير موجود: {approval_id}")
        from src.ops.contracts import now_iso
        decided_at = now_iso() if approved else (row["decided_at"] or "")
        with self._conn:
            self._conn.execute(
                "UPDATE approvals SET approved = ?, decided_by = ?, decided_at = ? "
                "WHERE id = ?",
                (int(approved), decided_by, decided_at, approval_id),
            )
        self.audit("approval.decided", approval_id,
                   {"approved": approved, "decided_by": decided_by})
        return Approval(
            mission_id=row["mission_id"], kind=row["kind"],
            subject=row["subject"], note=row["note"] or "",
            approved=approved, decided_by=decided_by, decided_at=decided_at,
            id=approval_id,
        )

    def approvals_for(self, mission_id: str) -> list[Approval]:
        rows = self._conn.execute(
            "SELECT * FROM approvals WHERE mission_id = ? ORDER BY id",
            (mission_id,)).fetchall()
        return [
            Approval(
                mission_id=r["mission_id"], kind=r["kind"],
                subject=r["subject"], note=r["note"] or "",
                approved=None if r["approved"] is None else bool(r["approved"]),
                decided_by=r["decided_by"] or "", decided_at=r["decided_at"] or "",
                id=r["id"],
            )
            for r in rows
        ]

    # ── الدروس ────────────────────────────────────────────────────────────

    def add_lesson(self, lesson: Lesson) -> Lesson:
        if not lesson.id:
            lesson = Lesson(
                text=lesson.text, scope=lesson.scope,
                confidence=lesson.confidence,
                source_mission_id=lesson.source_mission_id,
                applied_count=lesson.applied_count, active=lesson.active,
                id=new_id("org-l", lesson.text, lesson.scope),
            )
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO lessons (id, text, scope, confidence, "
                "source_mission_id, applied_count, active, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    lesson.id, lesson.text, lesson.scope, lesson.confidence,
                    lesson.source_mission_id, lesson.applied_count,
                    int(lesson.active), self._now(),
                ),
            )
        return lesson

    def lessons_active(self) -> list[Lesson]:
        """الدروس النشطة مرتبة بالثقة ثم عدد التطبيق — قراءة حتمية."""
        rows = self._conn.execute(
            "SELECT * FROM lessons WHERE active = 1 "
            "ORDER BY confidence DESC, applied_count DESC, id").fetchall()
        return [
            Lesson(
                text=r["text"], scope=r["scope"], confidence=float(r["confidence"]),
                source_mission_id=r["source_mission_id"] or "",
                applied_count=int(r["applied_count"]),
                active=bool(r["active"]), id=r["id"],
            )
            for r in rows
        ]

    def lesson_bump(self, lesson_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE lessons SET applied_count = applied_count + 1 "
                "WHERE id = ?", (lesson_id,))
        self.audit("lesson.applied", lesson_id, {})

    # ── المقاييس ──────────────────────────────────────────────────────────

    def record_metric(self, name: str, value: float, tags: dict[str, Any]) -> str:
        mid = new_id("org-mt", name, json.dumps(tags, sort_keys=True),
                     str(value))
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO org_metrics (id, name, value, tags, "
                "created_at) VALUES (?, ?, ?, ?, ?)",
                (mid, name, float(value),
                 json.dumps(tags, sort_keys=True, ensure_ascii=False),
                 self._now()),
            )
        return mid

    def metrics_snapshot(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM org_metrics ORDER BY name, id").fetchall()
        return [
            {
                "name": r["name"], "value": float(r["value"]),
                "tags": json.loads(r["tags"] or "{}"),
            }
            for r in rows
        ]

    # ── العدّادات ─────────────────────────────────────────────────────────

    def counts(self) -> dict[str, int]:
        """عدّادات عالية المستوى — استعلامات ثابتة للوحة والتقارير."""
        tables = ("missions", "tasks", "agent_runs", "reviews", "findings",
                  "claims", "evidence", "approvals", "lessons", "org_metrics")
        out: dict[str, int] = {}
        for t in tables:
            row = self._conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()
            out[t] = int(row["c"])
        return out

    def _now(self) -> str:
        from src.ops.contracts import now_iso
        return now_iso()

    def close(self) -> None:
        with self._lock:
            self._conn._conn.close()  # noqa: SLF001 — إغلاق الاتصال الخام فقط
