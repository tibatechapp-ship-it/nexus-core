"""
Learning Loop — Capture agent experiences for continuous improvement.

Records agent experiences (task, input, output, outcome) to a JSONL file.

Features:
- Thread-safe file locking (fcntl/msvcrt)
- Append-only JSONL storage
- SHA256 input hashing for dedup
- Memory-safe streaming (load_recent, stream_all)
- Stats: success_rate, avg_duration, by_agent breakdown
"""
import os
import json
import time
import hashlib
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional, Iterator
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field

# Cross-platform file locking
try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False
    try:
        import msvcrt
        HAS_MSVCRT = True
    except ImportError:
        HAS_MSVCRT = False

logger = logging.getLogger("core.learning_loop")


@dataclass
class Experience:
    experience_id: str
    agent: str
    task: str
    input_hash: str
    input_size: int
    output_summary: str
    outcome: str
    duration: float
    provider: str = ""
    model: str = ""
    error: str = ""
    user_feedback: str = ""
    tags: List[str] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.experience_id:
            raw = f"{self.agent}:{self.input_hash}:{self.timestamp}"
            self.experience_id = hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict:
        return asdict(self)


class LearningLoop:
    def __init__(self, storage_path: Optional[Path] = None):
        base = os.environ.get(
            "NOVAMIND_HOME",
            str(Path(__file__).resolve().parent.parent),
        )
        if storage_path is None:
            storage_path = Path(base) / "memory" / "experiences.jsonl"
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        logger.info(f"LearningLoop storage: {self.storage_path}")

    def _acquire_file_lock(self, f):
        if HAS_FCNTL:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        elif HAS_MSVCRT:
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)

    def _release_file_lock(self, f):
        if HAS_FCNTL:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        elif HAS_MSVCRT:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception:
                pass

    def record(self, agent, task, input_data, output, outcome,
               duration=0.0, provider="", model="", error="",
               user_feedback="", tags=None):
        input_hash = hashlib.sha256(input_data.encode()).hexdigest()
        if isinstance(output, dict):
            summary = output.get("summary") or output.get("verdict") or str(output)[:200]
        else:
            summary = str(output)[:200]

        exp = Experience(
            experience_id="", agent=agent, task=task,
            input_hash=input_hash, input_size=len(input_data),
            output_summary=summary, outcome=outcome,
            duration=duration, provider=provider, model=model,
            error=error[:500], user_feedback=user_feedback,
            tags=tags or [],
        )

        try:
            with self._lock:
                with open(self.storage_path, "a", encoding="utf-8") as f:
                    self._acquire_file_lock(f)
                    try:
                        f.write(json.dumps(exp.to_dict(), ensure_ascii=False) + "\n")
                        f.flush()
                        os.fsync(f.fileno())
                    finally:
                        self._release_file_lock(f)
        except Exception as e:
            logger.error(f"record failed: {e}")

        return exp

    def stream_all(self) -> Iterator[Experience]:
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield Experience(**json.loads(line))
                    except Exception:
                        continue
        except Exception as e:
            logger.error(f"stream error: {e}")

    def load_all(self) -> List[Experience]:
        return list(self.stream_all())

    def load_recent(self, limit: int = 100) -> List[Experience]:
        if not self.storage_path.exists():
            return []
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            recent = lines[-limit:] if len(lines) > limit else lines
            out = []
            for line in recent:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(Experience(**json.loads(line)))
                except Exception:
                    continue
            return out
        except Exception:
            return []

    def for_agent(self, agent: str) -> List[Experience]:
        return [e for e in self.stream_all() if e.agent == agent]

    def stats(self, agent: Optional[str] = None) -> Dict:
        exps = self.for_agent(agent) if agent else self.load_all()
        if not exps:
            return {"total": 0}

        successes = sum(1 for e in exps if e.outcome == "success")
        failures = sum(1 for e in exps if e.outcome == "failure")
        partial = sum(1 for e in exps if e.outcome == "partial")

        by_agent: Dict[str, Dict] = {}
        for e in exps:
            if e.agent not in by_agent:
                by_agent[e.agent] = {"total": 0, "success": 0, "failure": 0}
            by_agent[e.agent]["total"] += 1
            if e.outcome == "success":
                by_agent[e.agent]["success"] += 1
            elif e.outcome == "failure":
                by_agent[e.agent]["failure"] += 1

        avg_dur = sum(e.duration for e in exps) / len(exps)

        return {
            "total": len(exps),
            "success": successes,
            "failure": failures,
            "partial": partial,
            "success_rate": round(successes / len(exps), 3),
            "avg_duration": round(avg_dur, 3),
            "by_agent": by_agent,
            "storage": str(self.storage_path),
        }

    def top_failures(self, limit: int = 10) -> List[Dict]:
        failures: Dict[str, int] = {}
        for e in self.stream_all():
            if e.outcome == "failure":
                failures[e.agent] = failures.get(e.agent, 0) + 1
        return [{"agent": a, "failures": c}
                for a, c in sorted(failures.items(), key=lambda x: -x[1])[:limit]]

    def clear(self, confirm: bool = False) -> Dict:
        if not confirm:
            raise RuntimeError("Pass confirm=True to clear (destructive!)")
        if not self.storage_path.exists():
            return {"status": "no_file"}
        backup = self.storage_path.with_suffix(".jsonl.bak")
        try:
            if backup.exists():
                backup.unlink()
            self.storage_path.rename(backup)
            return {"status": "cleared", "backup": str(backup)}
        except Exception as e:
            return {"status": "error", "error": str(e)}


learning_loop = LearningLoop()

__all__ = ["LearningLoop", "learning_loop", "Experience"]
