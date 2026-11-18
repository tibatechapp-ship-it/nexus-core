"""Durable, fail-closed snapshots for mission context and repository state.

A checkpoint is an immutable record. Restoring it never dispatches work.
Repository and worktree trees are fingerprinted before context is accepted.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, cast

from src.org.contracts import Claim, Mission
from src.org.departments import MissionContext
from src.org.repo_intel import ModuleInfo, RepoMap
from src.org.review import CouncilDecision
from src.org.sandbox import Worktree
from src.org.store import OrgError, OrgStore

CONTEXT_SNAPSHOT_SCHEMA = 1
_IGNORED_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "node_modules", "dist", "build",
}


def fingerprint_directory(root: str | Path, *, include_git: bool = True) -> dict[str, Any]:
    """Return a deterministic SHA-256 tree fingerprint without following symlinks."""
    base = Path(root).resolve(strict=True)
    if not base.is_dir():
        raise OrgError(f"مسار المستودع ليس مجلدًا: {base}")
    digest = hashlib.sha256()
    count = 0
    for current, dirs, files in os.walk(base, topdown=True, followlinks=False):
        current_path = Path(current)
        symlink_dirs = sorted(
            name for name in dirs if (current_path / name).is_symlink())
        for name in symlink_dirs:
            path = current_path / name
            rel = path.relative_to(base).as_posix()
            symlink_entry = {"path": rel, "type": "symlink", "target": os.readlink(path)}
            encoded = json.dumps(symlink_entry, sort_keys=True).encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            count += 1
        dirs[:] = sorted(
            name for name in dirs
            if name not in _IGNORED_DIRS and name not in symlink_dirs
        )
        for name in sorted(files):
            path = current_path / name
            rel = path.relative_to(base).as_posix()
            if path.is_symlink():
                entry = {"path": rel, "type": "symlink", "target": os.readlink(path)}
                encoded = json.dumps(entry, sort_keys=True).encode("utf-8")
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
                count += 1
                continue
            if not path.is_file():
                continue
            file_hash = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    file_hash.update(chunk)
            entry = f"{rel}\0file\0{file_hash.hexdigest()}".encode("utf-8")
            digest.update(len(entry).to_bytes(8, "big"))
            digest.update(entry)
            count += 1

    result: dict[str, Any] = {
        "algorithm": "sha256-tree-v1",
        "root": str(base),
        "digest": digest.hexdigest(),
        "files": count,
    }
    if include_git:
        result["git_head"] = _git_value(base, "rev-parse", "HEAD")
        result["git_branch"] = _git_value(base, "branch", "--show-current")
    return result


def _git_value(root: Path, *args: str) -> str:
    """Read fixed git metadata commands only; never invokes repository scripts."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True, capture_output=True, text=True, timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip()


def _persist_worktree(worktree: Worktree | None, mission_id: str,
                      state_root: Path, repo_root: Path) -> tuple[str, str]:
    if worktree is None:
        return "", ""
    source = worktree.root.resolve(strict=True)
    if not source.is_dir():
        raise OrgError("نسخة العمل غير موجودة عند إنشاء checkpoint")
    state_root = state_root.resolve()
    if state_root == repo_root or repo_root in state_root.parents:
        raise OrgError("مخزن سياق المهام يجب أن يكون خارج المستودع")
    mission_dir = state_root / mission_id
    mission_dir.mkdir(parents=True, exist_ok=True)
    final = mission_dir / f"worktree-{uuid.uuid4().hex}"
    staging = Path(tempfile.mkdtemp(prefix=".checkpoint-", dir=mission_dir))
    try:
        for current, dirs, files in os.walk(source, topdown=True, followlinks=False):
            current_path = Path(current)
            rel_dir = current_path.relative_to(source)
            target_dir = staging / rel_dir
            target_dir.mkdir(parents=True, exist_ok=True)
            for name in list(dirs):
                item = current_path / name
                if item.is_symlink():
                    raise OrgError(f"رابط رمزي داخل نسخة العمل غير مدعوم: {item}")
            for name in sorted(files):
                item = current_path / name
                if item.is_symlink() or not item.is_file():
                    raise OrgError(f"ملف غير عادي داخل نسخة العمل: {item}")
                target = target_dir / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
        os.replace(staging, final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    worktree_fingerprint = fingerprint_directory(final, include_git=False)
    return str(final), str(worktree_fingerprint["digest"])


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(cast(Any, value))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise OrgError(f"نوع غير قابل للتخزين في سياق المهمة: {type(value).__name__}")


def save_mission_context_snapshot(
    store: OrgStore, ctx: MissionContext, state_root: str | Path,
) -> dict[str, Any]:
    """Persist context and an immutable worktree copy after validating source."""
    mission = store.mission_get(ctx.mission.id)
    if mission is None:
        raise OrgError(f"مهمة غير موجودة: {ctx.mission.id}")
    repo_root = Path(mission.repo_path).resolve(strict=True)
    repo_fingerprint = fingerprint_directory(repo_root)
    state_path = Path(state_root).expanduser().resolve()
    worktree_path, worktree_fingerprint = _persist_worktree(
        ctx.worktree, mission.id, state_path, repo_root)
    repo_map = ctx.repo_map.to_dict() if ctx.repo_map is not None else None
    payload = {
        "schema_version": CONTEXT_SNAPSHOT_SCHEMA,
        "mission": mission.to_dict(),
        "context": {
            "repo_map": repo_map,
            "intel_summary": _json_value(ctx.intel_summary),
            "affected": _json_value(ctx.affected),
            "originals": _json_value(ctx.originals),
            "diff_text": ctx.diff_text,
            "changed_files": list(ctx.changed_files),
            "dev_notes": ctx.dev_notes,
            "dev_risks": _json_value(ctx.dev_risks),
            "security_report": _json_value(ctx.security_report),
            "baseline_tests": _json_value(ctx.baseline_tests),
            "patched_tests": _json_value(ctx.patched_tests),
            "council": _json_value(ctx.council) if ctx.council else None,
            "claims": [_json_value(claim) for claim in ctx.claims],
            "pr_text": _json_value(ctx.pr_text),
            "usage": _json_value(ctx.usage),
        },
    }
    return store.save_mission_context_snapshot(
        mission.id, payload, repo_fingerprint,
        worktree_path=worktree_path,
        worktree_fingerprint=worktree_fingerprint,
        schema_version=CONTEXT_SNAPSHOT_SCHEMA,
    )


def restore_mission_context(
    store: OrgStore, mission_id: str, state_root: str | Path,
    expected_repo_root: str | Path | None = None,
) -> MissionContext:
    """Restore context only when source and persisted worktree fingerprints match."""
    snapshot = store.mission_context_snapshot_get(mission_id)
    if snapshot is None:
        raise OrgError(f"لا توجد لقطة سياق محفوظة للمهمة: {mission_id}")
    if int(snapshot["schema_version"]) != CONTEXT_SNAPSHOT_SCHEMA:
        raise OrgError("إصدار لقطة سياق المهمة غير مدعوم")
    payload = snapshot["payload"]
    if int(payload.get("schema_version", -1)) != CONTEXT_SNAPSHOT_SCHEMA:
        raise OrgError("محتوى لقطة السياق لا يطابق إصدار المخطط")
    mission_data = payload.get("mission")
    if not isinstance(mission_data, dict) or mission_data.get("id") != mission_id:
        raise OrgError("هوية المهمة داخل لقطة السياق غير مطابقة")
    mission = Mission.from_dict(mission_data)
    repo_root = Path(mission.repo_path).resolve(strict=True)
    if expected_repo_root is not None and repo_root != Path(expected_repo_root).resolve():
        raise OrgError("مسار المستودع الحالي لا يطابق مسار المهمة المحفوظ")
    current_fingerprint = fingerprint_directory(repo_root)
    if current_fingerprint != snapshot["repo_fingerprint"]:
        raise OrgError("بصمة المستودع تغيّرت؛ الاستئناف الآلي مرفوض ويتطلب مراجعة بشرية")

    context_data = payload.get("context")
    if not isinstance(context_data, dict):
        raise OrgError("بيانات سياق المهمة تالفة أو غير صالحة")
    ctx = MissionContext(mission=mission)
    for name in (
        "intel_summary", "affected", "originals", "diff_text", "changed_files",
        "dev_notes", "dev_risks", "security_report", "baseline_tests",
        "patched_tests", "pr_text", "usage",
    ):
        if name in context_data:
            setattr(ctx, name, context_data[name])

    repo_map_data = context_data.get("repo_map")
    if repo_map_data is not None:
        if not isinstance(repo_map_data, dict):
            raise OrgError("خريطة المستودع المحفوظة غير صالحة")
        ctx.repo_map = RepoMap(
            root=str(repo_map_data["root"]),
            modules=[ModuleInfo(**item) for item in repo_map_data.get("modules", [])],
            languages=dict(repo_map_data.get("languages", {})),
            files_scanned=int(repo_map_data.get("files_scanned", 0)),
            files_skipped_unchanged=int(
                repo_map_data.get("files_skipped_unchanged", 0)),
        )

    council_data = context_data.get("council")
    if council_data is not None:
        ctx.council = CouncilDecision(**council_data)
    ctx.claims = [Claim(**item) for item in context_data.get("claims", [])]

    worktree_path = str(snapshot.get("worktree_path") or "")
    expected_worktree = str(snapshot.get("worktree_fingerprint") or "")
    if bool(worktree_path) != bool(expected_worktree):
        raise OrgError("بيانات نسخة العمل المحفوظة غير مكتملة")
    if worktree_path:
        state_path = Path(state_root).expanduser().resolve(strict=True)
        restored_path = Path(worktree_path).resolve(strict=True)
        if state_path not in restored_path.parents:
            raise OrgError("مسار نسخة العمل خارج مخزن الحالة المصرح")
        actual = fingerprint_directory(restored_path, include_git=False)
        if actual["digest"] != expected_worktree:
            raise OrgError("بصمة نسخة العمل تغيّرت؛ الاستئناف مرفوض")
        ctx.worktree = Worktree(root=restored_path, _owned=False)
    return ctx
