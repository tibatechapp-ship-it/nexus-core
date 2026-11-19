"""العزل التنفيذي — تشغيل اختبارات وأوامر المستودع داخل حدود صارمة.

القواعد المعلنة (نفس سياسة الطبقة التشغيلية ``src.ops.verdict``):

* **كل تنفيذ كود مستودع داخل العزل**: حدود ذاكرة (``RLIMIT_AS``) ومعالج
  (``RLIMIT_CPU``) ومهلة قاسية وبيئة مُنقّحة بلا أسرار ولا توكنات موروثة.
* **الشبكة قابلة للإغلاق وليست مضمونة على مستوى النواة**: العزل هنا
  على مستوى العملية؛ الحجب الصارم للشبكة يتطلّب مشغّل حاويات —
  ``WorkspaceRunner.container_runner`` هو الخطّاف المعلن له، وغيابه
  يُنزَل الثقة في التقرير لا الصدق.
* **لا تدمير للمستودع الأصلي**: الاختبارات تعمل على **نسخة عمل
  مستقلة** من الملفات المتأثرة — الأصل للقراءة فقط افتراضيًا.
* **كل تنفيذ ينتج دليلًا**: ``RunResult`` يحمل الأمر والرمز والمخرجات
  والزمن — قابل للتخزين كدليل ``test_result`` أو ``replay``.
"""

from __future__ import annotations

import os
import resource
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

__all__ = ["RunResult", "SandboxLimits", "WorkspaceRunner"]

#: مفاتيح البيئة التي لا تُورَّث للعملية المعزولة أبدًا.
_STRIPPED_ENV_KEYS = ("token", "secret", "key", "password", "credential")


@dataclass(frozen=True)
class SandboxLimits:
    """حدود العزل المعلنة — نفس قيم السياسة التشغيلية افتراضيًا."""

    timeout_s: int = 120
    mem_mb: int = 512
    cpu_s: int = 60
    network: bool = False
    container_runner: str = ""   # خطّاف حاويات معلن؛ فراغه = عزل عملية


@dataclass(frozen=True)
class RunResult:
    """نتيجة تنفيذ معزول — دليل كامل قابل للتخزين."""

    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False
    isolation: str = "process"
    cwd_label: str = ""

    def summary(self) -> str:
        """سطر ملخص حتمي للدليل."""
        state = "مهلة" if self.timed_out else f"رمز {self.returncode}"
        return f"{self.command[:1]} → {state} في {self.duration_ms:.0f}ms"

    def to_detail(self) -> dict[str, Any]:
        """تفصيل الدليل للمخزن — مخرجات مقصوصة بسقف معلن."""
        cap = 8000
        return {
            "command": self.command,
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "duration_ms": round(self.duration_ms, 2),
            "isolation": self.isolation,
            "cwd_label": self.cwd_label,
            "stdout": self.stdout[:cap],
            "stderr": self.stderr[:cap],
        }


def _preexec_limits(limits: SandboxLimits) -> None:
    """تطبيق حدود الموارد في العملية الابن فقط."""
    try:
        mem = limits.mem_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_s, limits.cpu_s + 1))
    except (ValueError, OSError):  # pragma: no cover — بيئات بلا rlimit
        pass


def _sanitized_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """بيئة مُنقّحة — لا مفتاح ولا سر ولا توكن موروث."""
    clean = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": tempfile.gettempdir(),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
    }
    for k, v in (extra or {}).items():
        clean[k] = v
    return clean


class WorkspaceRunner:
    """مُشغّل أوامر معزول على مجلد عمل — أساس قسم الجودة والتحقق."""

    def __init__(self, limits: SandboxLimits | None = None) -> None:
        self.limits = limits or SandboxLimits()

    def run(self, command: list[str], workspace: Path,
            extra_env: dict[str, str] | None = None) -> RunResult:
        """تنفيذ أمر داخل مجلد عمل معزول بحدود المعلنة."""
        t0 = time.time()
        timed_out = False
        try:
            proc = subprocess.run(
                command,
                cwd=str(workspace),
                env=_sanitized_env(extra_env),
                capture_output=True,
                text=True,
                timeout=self.limits.timeout_s,
                preexec_fn=(lambda: _preexec_limits(self.limits)),
                check=False,
            )
            returncode, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            returncode = -1
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        except FileNotFoundError as exc:
            # أمر غير موجود — دليل فشل صريح لا استثناء يُسقط المُشغّل
            returncode = -2
            stdout, stderr = "", f"أمر غير موجود: {exc.filename}"
        duration = (time.time() - t0) * 1000.0
        isolation = self.limits.container_runner or "process"
        return RunResult(
            command=command, returncode=returncode, stdout=stdout,
            stderr=stderr, duration_ms=duration, timed_out=timed_out,
            isolation=isolation, cwd_label=workspace.name,
        )

    def run_python_tests(self, workspace: Path, *,
                         target: str = "") -> RunResult:
        """تشغيل اختبارات pytest داخل نسخة العمل المعزولة."""
        cmd = ["python3", "-m", "pytest", "-q", "--no-header"]
        if target:
            cmd.append(target)
        return self.run(cmd, workspace)

    def run_python(self, code: str) -> RunResult:
        """تشغيل مقتطف Python معزول (مسبار تحقق) — بلا مجلد مستودع."""
        with tempfile.TemporaryDirectory(prefix="org-probe-") as tmp:
            script = Path(tmp) / "probe.py"
            script.write_text(code, encoding="utf-8")
            return self.run(["python3", "probe.py"], Path(tmp))


@dataclass
class Worktree:
    """نسخة عمل مستقلة من ملفات المستودع — الأصل للقراءة لا للتخريب.

    تُنسخ الملفات المتأثرة فقط (أو المجلد المعلن) إلى مجلد مؤقت؛
    الرقعة تُطبَّق هنا والاختبارات تُشغَّل هنا، والأصل لا يُلمس.
    """

    root: Path
    _owned: bool = field(default=False, repr=False)

    @classmethod
    def from_source(cls, source: Path, files: list[str] | None = None,
                    whole: bool = False) -> "Worktree":
        """نسخ ملفات/مجلدات معلنة من المصدر إلى مجلد مؤقت مملوك."""
        tmp = Path(tempfile.mkdtemp(prefix="org-worktree-"))
        wt = cls(root=tmp)
        wt._owned = True
        src = Path(source)
        if whole:
            for item in sorted(src.iterdir()):
                if item.name in (".git", "__pycache__", ".venv", "node_modules"):
                    continue
                target = tmp / item.name
                if item.is_dir():
                    _copy_tree(item, target)
                else:
                    target.write_bytes(item.read_bytes())
        else:
            for rel in files or []:
                src_file = src / rel
                if not src_file.is_file():
                    continue
                dst = tmp / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(src_file.read_bytes())
        return wt

    def write(self, rel_path: str, content: str) -> None:
        """كتابة ملف داخل نسخة العمل — المسار مقيد داخل الجذر."""
        target = (self.root / rel_path).resolve()
        if self.root.resolve() not in target.parents:
            raise ValueError(f"مسار خارج نسخة العمل مرفوض: {rel_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def read(self, rel_path: str) -> str:
        target = (self.root / rel_path).resolve()
        if self.root.resolve() not in target.parents:
            raise ValueError(f"مسار خارج نسخة العمل مرفوض: {rel_path}")
        return target.read_text(encoding="utf-8")

    def apply_changes(self, changes: list[dict[str, str]]) -> list[str]:
        """تطبيق ملفات مُعدَّلة من وكيل التطوير — يعيد قائمة المسارات."""
        applied: list[str] = []
        for change in changes:
            path = change.get("path", "")
            content = change.get("content", "")
            if not path or not isinstance(content, str):
                continue
            self.write(path, content)
            applied.append(path)
        return applied

    def apply_repair_steps(self, steps: list[dict[str, Any]]) -> list[str]:
        """Apply validated coder RepairPlan operations atomically to this worktree.

        Only explicit edit/create/delete operations are accepted. All paths and
        preconditions are checked before the first write; on an I/O failure the
        original bytes are restored.
        """
        root = self.root.resolve()
        staged: list[tuple[Path, str, bytes | None]] = []
        seen: set[str] = set()
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError("repair step must be an object")
            rel = step.get("file")
            action = step.get("action")
            if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
                raise ValueError("repair step has an unsafe path")
            rel_path = Path(rel)
            if ".." in rel_path.parts or "\\" in rel:
                raise ValueError(f"unsafe repair path: {rel!r}")
            normalized = rel_path.as_posix()
            if normalized in seen:
                raise ValueError(f"duplicate repair path: {normalized!r}")
            seen.add(normalized)
            target = (root / rel_path).resolve()
            if not target.is_relative_to(root) or target == root:
                raise ValueError(f"repair path escapes worktree: {rel!r}")
            cursor = root
            for part in rel_path.parts:
                cursor = cursor / part
                if cursor.is_symlink():
                    raise ValueError(f"symlink repair target rejected: {rel!r}")
            if action == "create":
                if target.exists():
                    raise ValueError(f"refusing to overwrite existing file: {rel!r}")
                content = step.get("patch_hint")
                if not isinstance(content, str):
                    raise ValueError(f"create content is invalid: {rel!r}")
                staged.append((target, action, content.encode("utf-8")))
            elif action == "edit":
                find = step.get("find")
                replacement = step.get("patch_hint")
                if not isinstance(find, str) or not find or not isinstance(replacement, str):
                    raise ValueError(f"edit patch is invalid: {rel!r}")
                if not target.is_file():
                    raise FileNotFoundError(f"edit target missing: {rel!r}")
                original = target.read_bytes()
                try:
                    text = original.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError(f"edit target is not UTF-8: {rel!r}") from exc
                if text.count(find) != 1:
                    raise ValueError(f"find block must match exactly once: {rel!r}")
                updated = text.replace(find, replacement, 1).encode("utf-8")
                staged.append((target, action, updated))
            elif action == "delete":
                if not target.is_file():
                    raise FileNotFoundError(f"delete target missing: {rel!r}")
                staged.append((target, action, None))
            else:
                raise ValueError(f"unknown repair action: {action!r}")

        snapshots: dict[Path, bytes | None] = {}
        applied: list[str] = []
        try:
            for target, action, content in staged:
                snapshots[target] = target.read_bytes() if target.is_file() else None
                if action == "delete":
                    target.unlink()
                else:
                    assert content is not None
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                applied.append(target.relative_to(root).as_posix())
        except OSError:
            for target, previous in reversed(list(snapshots.items())):
                try:
                    if previous is None:
                        target.unlink(missing_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(previous)
                except OSError:
                    pass
            raise
        return applied

    def cleanup(self) -> None:
        """حذف نسخة العمل المؤقتة — آمن لأنها مملوكة حتميًا."""
        if self._owned and self.root.exists():
            import shutil
            shutil.rmtree(self.root, ignore_errors=True)


def _copy_tree(src: Path, dst: Path) -> None:
    """نسخ شجرة مجلدات مع تخطي مخلفات التشغيل."""
    dst.mkdir(parents=True, exist_ok=True)
    for item in sorted(src.iterdir()):
        if item.name in ("__pycache__", ".git", ".venv", "node_modules"):
            continue
        target = dst / item.name
        if item.is_dir():
            _copy_tree(item, target)
        else:
            target.write_bytes(item.read_bytes())


def runner_from_ops_policy(policy: Any) -> WorkspaceRunner:
    """بناء مُشغّل من سياسة العزل التشغيلية المعلنة (دمج الموجتين).

    يقرأ حقول ``SandboxPolicy`` التشغيلية المعلنة (``cpu_seconds``,
    ``memory_bytes``, ``timeout_sec``, ``network``, ``container_runner``)
    ويحوّلها إلى حدود التنظيم — التعديل الافتراضي للحقول غير موجود:
    يقرأ ويحوّل فقط، وسياسة ``network != "none"`` مرفوضة في البناء
    التشغيلي أصلاً فلا تجاوز هنا.
    """
    timeout = int(getattr(policy, "timeout_sec", 120) or 120)
    container = getattr(policy, "container_runner", None)
    limits = SandboxLimits(
        timeout_s=timeout,
        mem_mb=int(getattr(policy, "memory_bytes", 512 * 1024 * 1024)
                   // (1024 * 1024)) or 512,
        cpu_s=max(1, int(getattr(policy, "cpu_seconds", timeout) or timeout)),
        network=str(getattr(policy, "network", "none")) != "none",
        container_runner="container" if callable(container) else "",
    )
    return WorkspaceRunner(limits)
