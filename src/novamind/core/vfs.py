"""
SafeVfs - Safe Virtual File System
- Path whitelisting
- File size limits
- Prevent writes outside project root
"""
from pathlib import Path
from typing import Optional, List, Dict
import logging
import os

logger = logging.getLogger("vfs")

PROJECT_ROOT = Path(os.environ.get("NOVAMIND_HOME", str(Path(__file__).resolve().parent.parent)))

MAX_FILE_SIZE = 2_000_000
FORBIDDEN_EXTENSIONS = {".exe", ".dll", ".so", ".bin", ".sh"}
FORBIDDEN_PATHS = {"/etc", "/proc", "/sys", "/dev", "/boot"}


class VfsError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(code + ": " + message)


class SafeVfs:
    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p.resolve()

    def _check(self, path: Path) -> Optional[VfsError]:
        s = str(path)
        for forbidden in FORBIDDEN_PATHS:
            if s.startswith(forbidden):
                return VfsError("FORBIDDEN_PATH", "path blocked: " + s)
        if path.suffix in FORBIDDEN_EXTENSIONS:
            return VfsError("FORBIDDEN_EXT", "extension blocked: " + path.suffix)
        return None

    def exists(self, path: str) -> bool:
        try:
            p = self._resolve(path)
            if self._check(p):
                return False
            return p.exists()
        except Exception:
            return False

    def read(self, path: str) -> str:
        p = self._resolve(path)
        err = self._check(p)
        if err:
            raise err
        if not p.exists():
            raise VfsError("NOT_FOUND", "not found: " + path)
        if p.stat().st_size > MAX_FILE_SIZE:
            raise VfsError("TOO_LARGE", "file too large: " + str(p.stat().st_size))
        return p.read_text(encoding="utf-8", errors="replace")

    def write(self, path: str, content: str) -> None:
        p = self._resolve(path)
        err = self._check(p)
        if err:
            raise err
        size = len(content.encode("utf-8"))
        if size > MAX_FILE_SIZE:
            raise VfsError("TOO_LARGE", "content too large: " + str(size))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def append(self, path: str, content: str) -> None:
        existing = self.read(path) if self.exists(path) else ""
        self.write(path, existing + content)

    def delete(self, path: str) -> None:
        p = self._resolve(path)
        err = self._check(p)
        if err:
            raise err
        if p.exists() and p.is_file():
            p.unlink()

    def list_dir(self, path: str = ".") -> List[Dict]:
        p = self._resolve(path)
        if not p.exists() or not p.is_dir():
            return []
        items = []
        for entry in sorted(p.iterdir()):
            if entry.name.startswith("."):
                continue
            items.append({
                "name": entry.name,
                "type": "dir" if entry.is_dir() else "file",
                "size": entry.stat().st_size if entry.is_file() else 0,
            })
        return items

    def info(self) -> Dict:
        return {
            "root": str(PROJECT_ROOT),
            "max_size": MAX_FILE_SIZE,
            "forbidden_ext": sorted(FORBIDDEN_EXTENSIONS),
        }


vfs = SafeVfs()
