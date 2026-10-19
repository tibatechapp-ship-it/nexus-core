"""مسارات قابلة للكتابة — سلسلة التراجع على Termux/Android.

الخلفية: وحدات طبقة novamind كانت تفترض ``/var/lib`` و``/var/log``. على
Android الجذر ``/`` للقراءة فقط (EROFS) ولا ``/var`` أصلًا، فكان
``Path("/var/log/…").mkdir(parents=True, exist_ok=True)`` يسقط بـ
``OSError`` — وهذا وحده كان يُفشل تحميل الوكلاء عبر ``novamind.agents.factory``
(اختبار ``test_no_load_errors``).

هذه الاختبارات تُثبت: (1) السلسلة تختار أول مسار قابل للكتابة وتتخطّى
غير القابل، (2) الجذر المضمون لا يُسقط استثناءً أبدًا، (3) كل وحدة كانت
تستخدم ``/var`` صارت تستخدم المسار القابل للكتابة.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from novamind import paths as P


# ── السلسلة نفسها ────────────────────────────────────────────────────────

def test_candidates_priority_order(monkeypatch, tmp_path):
    """env override أولًا، ثم المرغوبة، ثم cache المنزل، ثم مؤقّت النظام."""
    monkeypatch.setenv(P.DATA_DIR_ENV, str(tmp_path / "data"))
    got = P.candidates()
    assert got[0] == tmp_path / "data"
    assert got[1:3] == [Path("/var/lib/nexus"), Path("/var/tmp/nexus")]
    assert got[3] == Path.home() / ".cache" / "nexus"
    assert got[4] == Path(tempfile.gettempdir()) / "nexus"


def test_candidates_without_env_skips_the_override(monkeypatch):
    monkeypatch.delenv(P.DATA_DIR_ENV, raising=False)
    got = P.candidates()
    assert got[0] == Path("/var/lib/nexus")


def test_first_writable_skips_the_unbuildable_and_picks_the_next(tmp_path):
    """مرشّح لا يمكن إنشاؤه (أبوه ملف) يُتخطّى، ويُختار التالي."""
    blocker = tmp_path / "afile"
    blocker.write_text("x")
    bad = blocker / "sub"          # mkdir → NotADirectoryError (OSError)
    good = tmp_path / "ok"
    assert P.first_writable([bad, good]) == good


def test_first_writable_returns_none_when_nothing_works(tmp_path):
    blocker = tmp_path / "afile"
    blocker.write_text("x")
    assert P.first_writable([blocker / "a", blocker / "b"]) is None


def test_writable_root_falls_back_to_tempdir_when_all_candidates_fail(monkeypatch, tmp_path):
    """لا مرشّح صالح على الإطلاق ⇒ <tempdir>/nexus (مضمون) بلا استثناء."""
    blocker = tmp_path / "afile"
    blocker.write_text("x")
    monkeypatch.setattr(P, "candidates", lambda *a, **k: [blocker / "a", blocker / "b"])
    root = P.writable_root()
    assert root == Path(tempfile.gettempdir()) / "nexus"
    assert root.is_dir()
    assert os.access(root, os.W_OK)


def test_writable_root_skips_bad_preferred_and_returns_a_writable_dir(
    monkeypatch, tmp_path
):
    blocker = tmp_path / "afile"
    blocker.write_text("x")
    monkeypatch.delenv(P.DATA_DIR_ENV, raising=False)
    root = P.writable_root(preferred=(str(blocker / "x"), str(blocker / "y")))
    assert root.is_dir()
    assert os.access(root, os.W_OK)


def test_writable_root_honours_the_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(P.DATA_DIR_ENV, str(tmp_path / "root"))
    assert P.writable_root() == tmp_path / "root"


def test_writable_path_creates_the_parent(tmp_path, monkeypatch):
    monkeypatch.setenv(P.DATA_DIR_ENV, str(tmp_path / "root"))
    target = P.writable_path("nested/deep/file.json")
    assert target == tmp_path / "root" / "nested" / "deep" / "file.json"
    assert target.parent.is_dir()


# ── الوحدات التي كانت تفترض /var ─────────────────────────────────────────

def test_memory_engine_uses_novamind_home_when_set(monkeypatch, tmp_path):
    from novamind.memory import engine as mem

    monkeypatch.setenv("NOVAMIND_HOME", str(tmp_path / "nm"))
    assert mem._memory_dir() == tmp_path / "nm"


def test_memory_engine_dir_is_writable_without_novamind_home(monkeypatch, tmp_path):
    """هذا هو الانحدار الفعلي: بلا NOVAMIND_HOME كان المسار ``/var/lib/hive``."""
    from novamind.memory import engine as mem

    monkeypatch.delenv("NOVAMIND_HOME", raising=False)
    monkeypatch.setenv(P.DATA_DIR_ENV, str(tmp_path / "data"))
    resolved = mem._memory_dir()
    assert resolved.is_dir()
    assert os.access(resolved, os.W_OK)
    assert resolved == tmp_path / "data"


def test_memory_engine_dir_never_points_at_var_on_android(monkeypatch):
    """بلا أيّ إعداد: المسار يجب أن يكون قابلًا للكتابة لا ``/var/…``."""
    from novamind.memory import engine as mem

    monkeypatch.delenv("NOVAMIND_HOME", raising=False)
    monkeypatch.delenv(P.DATA_DIR_ENV, raising=False)
    resolved = mem._memory_dir()
    assert resolved.is_dir()
    assert os.access(resolved, os.W_OK)


def test_audit_log_env_override(monkeypatch, tmp_path):
    from novamind.security.audit import AuditLog

    target = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AUDIT_LOG_FILE", str(target))
    audit = AuditLog()
    audit.log("test", {"a": 1})
    assert target.exists()
    assert '"type": "test"' in target.read_text()


def test_audit_log_default_falls_back_to_a_writable_root(monkeypatch):
    from novamind.security.audit import AuditLog

    monkeypatch.delenv("AUDIT_LOG_FILE", raising=False)
    audit = AuditLog()
    audit.log("test", {"a": 1})
    assert audit.file.parent.is_dir()
    assert audit.file.exists()


def test_rbac_audit_falls_back_when_the_default_is_unwritable(monkeypatch, tmp_path):
    """نلتقط OSError (لا PermissionError فقط): EROFS ابن OSError."""
    from novamind.security.rbac_audit import RBACAudit

    blocker = tmp_path / "afile"
    blocker.write_text("x")
    monkeypatch.setenv("RBAC_AUDIT_LOG", str(blocker / "sub" / "rbac.jsonl"))
    audit = RBACAudit()
    # لم يُسقط استثناءً، والمسار النهائي قابل للكتابة
    assert audit.file.parent.is_dir()
    audit.log("agent", "read", True)
    assert audit.file.exists()


def test_project_manager_state_path_env_override(monkeypatch, tmp_path):
    from novamind.agents import project_manager as pm

    target = tmp_path / "pm.json"
    monkeypatch.setenv("NEXUS_PM_STATE", str(target))
    assert pm._state_path() == target


def test_project_manager_state_path_default_is_writable(monkeypatch):
    from novamind.agents import project_manager as pm

    monkeypatch.delenv("NEXUS_PM_STATE", raising=False)
    monkeypatch.delenv(P.DATA_DIR_ENV, raising=False)
    resolved = pm._state_path()
    assert resolved.parent.is_dir()


def test_auto_worker_state_path_env_override(monkeypatch, tmp_path):
    from novamind.security import auto_worker as aw

    target = tmp_path / "aw.json"
    monkeypatch.setenv("NEXUS_AUTO_WORKER_STATE", str(target))
    assert aw.AutoWorker._state_path() == target
