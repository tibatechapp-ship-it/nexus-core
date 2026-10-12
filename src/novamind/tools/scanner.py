#!/usr/bin/env python3
"""
PythonScanner — Enterprise-Grade File Discovery Engine
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Optional, Set

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDES: Set[str] = {
    ".git", ".svn", ".hg",
    "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", ".coverage", "htmlcov",
    ".venv", "venv", "env", ".env",
    "site-packages",
    "node_modules", "bower_components",
    "dist", "build", ".eggs",
    ".vscode", ".idea",
    "legacy", "rescue", "backups",
    "_archive", ".archive", ".backups",
    ".aider", ".cache",
    "tests", "test", "testing",
}

DEFAULT_PATTERNS: List[str] = [
    r"^hive_rescue_\d+",
    r"^merge_backup_\d+",
    r"^hive_full_backup_\d+",
    r"^hive_backup_\d+",
    r"^backup_before_",
    r".*_backup_\d+$",
    r"^tmp_",
    r"^generated_",
]

MAX_FILE_SIZE_MB: int = 10
STREAM_CHUNK_SIZE: int = 64 * 1024
THREAD_THRESHOLD: int = 100


@dataclass(frozen=True)
class PyFileInfo:
    path: Path
    relative_path: str
    size_bytes: int
    line_count: int
    last_modified: datetime
    content_hash: str = ""

    @property
    def size_kb(self) -> float:
        return round(self.size_bytes / 1024, 1)

    @property
    def age_days(self) -> float:
        delta = datetime.now() - self.last_modified
        return round(delta.total_seconds() / 86400, 1)

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "line_count": self.line_count,
            "last_modified": self.last_modified.isoformat(),
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PyFileInfo":
        return cls(
            path=Path(data["path"]),
            relative_path=data["relative_path"],
            size_bytes=data["size_bytes"],
            line_count=data["line_count"],
            last_modified=datetime.fromisoformat(data["last_modified"]),
            content_hash=data.get("content_hash", ""),
        )


class ScanError(Exception):
    pass


class PythonScanner:
    def __init__(
        self,
        root_path: Path,
        exclude_dirs: Optional[Set[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
        max_workers: int = 4,
        max_file_size_mb: int = MAX_FILE_SIZE_MB,
        git_aware: bool = False,
        cache_dir: Optional[Path] = None,
        use_threads: Optional[bool] = None,
    ):
        self.root_path = Path(root_path).resolve()
        if not self.root_path.exists():
            raise ScanError(f"Root path does not exist: {self.root_path}")

        self.exclude_dirs = exclude_dirs or DEFAULT_EXCLUDES
        self.max_workers = max_workers
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self.git_aware = git_aware
        self.use_threads = use_threads

        patterns = exclude_patterns or DEFAULT_PATTERNS
        self.pattern_re = (
            re.compile("|".join(f"({p})" for p in patterns))
            if patterns else None
        )

        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _should_exclude(self, path: Path) -> bool:
        if not self.exclude_dirs.isdisjoint(path.parts):
            return True
        if self.pattern_re and self.pattern_re.search(str(path)):
            return True
        return False

    def _is_safe_path(self, path: Path) -> bool:
        try:
            if not path.is_file():
                return False
            try:
                resolved = path.resolve(strict=True)
            except (OSError, RuntimeError):
                return False
            try:
                resolved.relative_to(self.root_path)
            except ValueError:
                logger.warning(f"Path escape: {path} -> {resolved}")
                return False
            if resolved.stat().st_size > self.max_file_size_bytes:
                logger.warning(f"File too large: {path}")
                return False
            return True
        except OSError as e:
            logger.debug(f"Safe check failed for {path}: {e}")
            return False

    def _discover_via_git(self) -> Iterator[Path]:
        try:
            result = subprocess.run(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.py"],
                cwd=self.root_path,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            for rel in result.stdout.strip().split("\n"):
                if rel:
                    path = self.root_path / rel
                    if path.is_file():
                        yield path
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning(f"git ls-files failed: {e}. Falling back to rglob.")
            yield from self._discover_via_rglob()

    def _discover_via_rglob(self) -> Iterator[Path]:
        for path in self.root_path.rglob("*.py"):
            if self._is_safe_path(path):
                yield path

    def discover(self) -> Iterator[Path]:
        source = self._discover_via_git if self.git_aware else self._discover_via_rglob
        count = 0
        for path in source():
            if self._should_exclude(path):
                continue
            if not path.is_file():
                continue
            count += 1
            yield path
        logger.info(f"Discovered {count} candidate files")

    @staticmethod
    def _count_lines_streaming(path: Path) -> int:
        count = 0
        last_byte = b""
        with open(path, "rb") as f:
            while True:
                chunk = f.read(STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                count += chunk.count(b"\n")
                last_byte = chunk[-1:]
        if last_byte and last_byte != b"\n":
            count += 1
        return count

    def _extract_metadata(self, path: Path) -> Optional[PyFileInfo]:
        try:
            stat = path.stat()
            if stat.st_size > self.max_file_size_bytes:
                logger.warning(f"File too large ({stat.st_size} bytes): {path}")
                return None
            line_count = self._count_lines_streaming(path)
            return PyFileInfo(
                path=path,
                relative_path=str(path.relative_to(self.root_path)),
                size_bytes=stat.st_size,
                line_count=line_count,
                last_modified=datetime.fromtimestamp(stat.st_mtime),
            )
        except FileNotFoundError:
            logger.debug(f"File disappeared: {path}")
            return None
        except PermissionError:
            logger.warning(f"Permission denied: {path}")
            return None
        except OSError as e:
            logger.error(f"I/O error on {path}: {e}")
            return None

    def _cache_key(self, path: Path) -> Optional[str]:
        if not self.cache_dir:
            return None
        try:
            stat = path.stat()
            raw = f"{path}:{stat.st_mtime}:{stat.st_size}"
            return hashlib.sha256(raw.encode()).hexdigest()[:16]
        except OSError:
            return None

    def _cache_load(self, key: str) -> Optional[PyFileInfo]:
        if not self.cache_dir or not key:
            return None
        cache_file = self.cache_dir / f"{key}.json"
        if not cache_file.exists():
            return None
        try:
            return PyFileInfo.from_dict(json.loads(cache_file.read_text()))
        except Exception as e:
            logger.debug(f"Cache miss for {key}: {e}")
            return None

    def _cache_save(self, key: str, info: PyFileInfo) -> None:
        if not self.cache_dir or not key:
            return
        try:
            cache_file = self.cache_dir / f"{key}.json"
            cache_file.write_text(json.dumps(info.to_dict(), ensure_ascii=False))
        except Exception as e:
            logger.debug(f"Cache save failed: {e}")

    def _process_file(self, path: Path) -> Optional[PyFileInfo]:
        key = self._cache_key(path)
        if key:
            cached = self._cache_load(key)
            if cached:
                return cached
        info = self._extract_metadata(path)
        if info and key:
            self._cache_save(key, info)
        return info

    def scan(
        self,
        detailed: bool = True,
        progress: bool = False,
        sort_by: str = "size",
    ) -> List[PyFileInfo]:
        paths = list(self.discover())
        if not paths:
            logger.warning("No Python files found.")
            return []

        iterator = paths
        if progress:
            try:
                from tqdm import tqdm
                iterator = tqdm(paths, desc="Scanning", unit="file")
            except ImportError:
                logger.info("tqdm not installed, no progress bar")

        if not detailed:
            return paths  # type: ignore

        use_threads = self.use_threads
        if use_threads is None:
            use_threads = len(paths) > THREAD_THRESHOLD

        results: List[PyFileInfo] = []

        if use_threads:
            logger.info(f"Using {self.max_workers} threads for {len(paths)} files")
            with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
                futures = {ex.submit(self._process_file, p): p for p in iterator}
                for fut in as_completed(futures):
                    try:
                        info = fut.result()
                        if info:
                            results.append(info)
                    except Exception as e:
                        logger.error(f"Thread failed: {futures[fut]}: {e}")
        else:
            logger.info(f"Single-threaded scan of {len(paths)} files")
            for p in iterator:
                info = self._process_file(p)
                if info:
                    results.append(info)

        sorters = {
            "size": lambda x: -x.size_bytes,
            "lines": lambda x: -x.line_count,
            "path": lambda x: x.relative_path,
            "mtime": lambda x: -x.last_modified.timestamp(),
        }
        return sorted(results, key=sorters.get(sort_by, sorters["size"]))


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    root = Path(sys.argv[1] if len(sys.argv) > 1 else "/public")
    scanner = PythonScanner(root, git_aware=True)
    files = scanner.scan()

    total_lines = sum(f.line_count for f in files)
    total_mb = sum(f.size_bytes for f in files) / (1024 * 1024)

    print()
    print("=" * 75)
    print("Scan Results")
    print("=" * 75)
    print(f"Files:  {len(files)}")
    print(f"Lines:  {total_lines:,}")
    print(f"Size:   {total_mb:.2f} MB")
    print()
    print("Top 20 largest:")
    print("-" * 75)
    for f in files[:20]:
        print(f"  {f.line_count:>6} Lns | {f.size_kb:>8.1f} KB | {f.relative_path}")
    print("=" * 75)
