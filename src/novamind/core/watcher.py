"""
FileWatcher - Monitors workspace for changes
- Scans workspace every N seconds
- Detects new/modified .py files
- Uses MD5 hash to avoid reprocessing
- No LLM dependency
"""
import asyncio
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Callable, Optional, Awaitable

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import WORKSPACE_DIR

logger = logging.getLogger("watcher")


class FileWatcher:
    def __init__(self, watch_dir=None, poll_interval=2.0):
        self.watch_dir = Path(watch_dir) if watch_dir else WORKSPACE_DIR
        self.poll_interval = poll_interval
        self.seen: Dict[str, str] = {}
        self.running = False
        self.on_change: Optional[Callable[[Path, str], Awaitable[None]]] = None
        self._stats = {"scanned": 0, "detected": 0, "errors": 0}

    def register_callback(self, callback):
        """Register an async callback to be called on file change."""
        self.on_change = callback

    def _file_hash(self, path: Path) -> str:
        """Computes MD5 hash of file content."""
        try:
            content = path.read_bytes()
            return hashlib.md5(content, usedforsecurity=False).hexdigest()
        except Exception:
            return ""

    def _scan_once(self):
        """Scans the workspace once, returns list of changed files."""
        changed = []

        if not self.watch_dir.exists():
            return changed

        for file in self.watch_dir.glob("*.py"):
            if file.name.startswith("_"):
                continue
            if file.name.endswith(".result.json"):
                continue

            try:
                h = self._file_hash(file)
                if not h:
                    continue

                key = str(file)
                if self.seen.get(key) != h:
                    self.seen[key] = h
                    changed.append(file)

                self._stats["scanned"] += 1
            except Exception as e:
                self._stats["errors"] += 1
                logger.warning("scan error on " + str(file) + ": " + str(e))

        return changed

    async def watch_loop(self):
        """Main watch loop."""
        self.running = True
        self.watch_dir.mkdir(parents=True, exist_ok=True)

        logger.info("watcher started on " + str(self.watch_dir) +
                    " (interval=" + str(self.poll_interval) + "s)")

        while self.running:
            try:
                changed = self._scan_once()

                for file in changed:
                    self._stats["detected"] += 1
                    logger.info("detected change: " + file.name)

                    if self.on_change:
                        try:
                            await self.on_change(file, file.read_text(encoding="utf-8", errors="replace"))
                        except Exception as e:
                            logger.error("callback error for " + file.name + ": " + str(e))

                await asyncio.sleep(self.poll_interval)

            except asyncio.CancelledError:
                logger.info("watcher cancelled")
                break
            except Exception as e:
                logger.error("watch loop error: " + str(e))
                await asyncio.sleep(self.poll_interval)

    def stop(self):
        self.running = False

    def stats(self):
        return dict(self._stats)


# Singleton
watcher = FileWatcher()
