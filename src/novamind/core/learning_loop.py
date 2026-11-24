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
import math
import re
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


class LearningStorageError(RuntimeError):
    """Raised when learning data could not be durably persisted."""


def sanitize_learning_text(value: str, max_length: int | None = 4000) -> str:
    """Redact common credential formats before learning data reaches disk."""
    if not isinstance(value, str):
        raise TypeError("learning text must be a string")
    text = re.sub(
        r"(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)[A-Za-z0-9._~+/-]+=*",
        r"\1[REDACTED]",
        value,
    )
    text = re.sub(
        r"""(?i)(["']?(?:api[_-]?key|secret|password|token)["']?\s*[:=]\s*["']?)[^\s,"']+""",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(
        r"""(?i)(authorization\s*[:=]\s*)(?!bearer\s|basic\s)[^\s,"']+""",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(
        r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})\b",
        "[REDACTED]",
        text,
    )
    text = re.sub(
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
        "[REDACTED]",
        text,
    )
    return text if max_length is None else text[:max_length]


def _redact_learning_text(value: str) -> str:
    """Compatibility helper for agent-facing redaction."""
    return sanitize_learning_text(value, max_length=None)


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
    input_summary: str = ""

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
        configured_path = os.environ.get("NOVAMIND_LEARNING_LOOP_PATH")
        if storage_path is None and configured_path:
            storage_path = Path(configured_path)
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

    def record(
        self,
        agent,
        task,
        input_data,
        output,
        outcome,
        duration=0.0,
        provider="",
        model="",
        error="",
        user_feedback="",
        tags=None,
        input_summary="",
    ):
        """Validate, redact and durably append one learning experience."""
        if not isinstance(agent, str) or not agent.strip():
            raise ValueError("agent must be a non-empty string")
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be a non-empty string")
        if not isinstance(input_data, str):
            raise TypeError("input_data must be a string")
        if not isinstance(outcome, str) or not outcome.strip():
            raise ValueError("outcome must be a non-empty string")
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or duration < 0
        ):
            raise ValueError("duration must be a finite, non-negative number")
        duration = float(duration)
        if len(input_data.encode("utf-8")) > 1_048_576:
            raise ValueError("input_data exceeds the 1 MiB learning record limit")
        text_fields = (provider, model, error, user_feedback, input_summary)
        if not all(isinstance(value, str) for value in text_fields):
            raise TypeError(
                "provider, model, error, user_feedback, and input_summary must be strings"
            )
        raw_tags = [] if tags is None else tags
        if not isinstance(raw_tags, (list, tuple)) or any(
            not isinstance(tag, str) or not tag.strip() for tag in raw_tags
        ):
            raise TypeError("tags must be a list of non-empty strings")

        sanitized_input = sanitize_learning_text(input_data, max_length=None)
        if len(sanitized_input.encode("utf-8")) > 1_048_576:
            raise ValueError("sanitized input_data exceeds the 1 MiB learning record limit")
        input_hash = hashlib.sha256(sanitized_input.encode("utf-8")).hexdigest()
        if isinstance(output, dict):
            summary = output.get("summary") or output.get("verdict") or str(output)
        else:
            summary = str(output)

        exp = Experience(
            experience_id="",
            agent=sanitize_learning_text(agent.strip(), max_length=100),
            task=sanitize_learning_text(task.strip(), max_length=500),
            input_hash=input_hash,
            input_size=len(sanitized_input),
            output_summary=sanitize_learning_text(str(summary), max_length=500),
            outcome=sanitize_learning_text(outcome.strip(), max_length=100),
            duration=duration,
            provider=sanitize_learning_text(provider, max_length=100),
            model=sanitize_learning_text(model, max_length=100),
            error=sanitize_learning_text(error, max_length=500),
            user_feedback=sanitize_learning_text(user_feedback, max_length=200),
            tags=[sanitize_learning_text(tag, max_length=100) for tag in raw_tags],
            input_summary=sanitize_learning_text(input_summary, max_length=4000),
        )

        try:
            with self._lock:
                with open(self.storage_path, "a", encoding="utf-8") as f:
                    self._acquire_file_lock(f)
                    start_offset = f.tell()
                    try:
                        f.write(json.dumps(exp.to_dict(), ensure_ascii=False) + "\n")
                        f.flush()
                        os.fsync(f.fileno())
                    except Exception:
                        # Best-effort rollback prevents a failed append from leaving
                        # a truncated JSONL record that poisons subsequent reads.
                        try:
                            f.seek(start_offset)
                            f.truncate()
                            f.flush()
                            os.fsync(f.fileno())
                        except Exception:
                            logger.error(
                                "learning ledger rollback failed; manual integrity check required"
                            )
                        raise
                    finally:
                        self._release_file_lock(f)
        except Exception as e:
            # Avoid logging raw OS exception text, which may contain sensitive paths.
            logger.error(
                "record failed; durable write unavailable (%s)",
                type(e).__name__,
            )
            raise LearningStorageError("Could not persist learning experience") from e

        return exp

    def learn_from_pr_review(self, repo: str, pr_num: int, issues: List[Dict]) -> Dict:
        """Store review classifications as lessons without retaining source text."""
        import re

        if not isinstance(repo, str) or not repo.strip():
            raise ValueError("repo must be a non-empty string")
        if isinstance(pr_num, bool) or not isinstance(pr_num, int) or pr_num < 0:
            raise ValueError("pr_num must be a non-negative integer")
        if not isinstance(issues, list):
            raise TypeError("issues must be a list")

        safe_issues = []
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            safe = {}
            # Keep only classification labels; filenames and free-form text can
            # expose private paths, code snippets, credentials, or prompt injection.
            for key in ("category", "severity", "rule_id"):
                value = issue.get(key)
                if isinstance(value, str) and value.strip():
                    normalized = re.sub(r"[^A-Za-z0-9_.:-]+", "_", value.strip())[:100]
                    if normalized:
                        safe[key] = normalized
            if safe:
                safe_issues.append(safe)

        if not safe_issues:
            return {"learned": 0, "experience_ids": []}

        task = f"PR review: {repo.strip()}#{pr_num}"
        payload = json.dumps(safe_issues, ensure_ascii=False, sort_keys=True)
        patterns = sorted({
            "/".join(item.get(key, "-") for key in ("category", "severity", "rule_id"))
            for item in safe_issues
        })[:20]
        summary = (f"PR review classification patterns ({len(safe_issues)} findings): "
                   + "; ".join(patterns))[:1000]
        exp = self.record(
            agent="pr_reviewer",
            task=task,
            input_data=payload,
            output={"summary": summary},
            outcome="partial",
            duration=0.0,
            tags=["pr-review", "review-findings"],
        )
        return {"learned": len(safe_issues), "experience_ids": [exp.experience_id]}

    def record_feedback(self, pattern: str, liked: bool, context: str = "", source: str = "user") -> Dict:
        """Persist user preference feedback without treating it as task success."""
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError("pattern must be a non-empty string")
        if not isinstance(liked, bool):
            raise TypeError("liked must be a bool")
        if not isinstance(context, str) or not isinstance(source, str):
            raise TypeError("context and source must be strings")
        payload = json.dumps({
            "pattern": pattern.strip()[:500],
            "context": context.strip()[:500],
            "liked": liked,
        }, ensure_ascii=False, sort_keys=True)
        safe_pattern = " ".join(pattern.strip().split())[:160]
        safe_pattern = re.sub(
            r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*\S+",
            r"\1=[REDACTED]",
            safe_pattern,
        )
        feedback_summary = f"User feedback ({'liked' if liked else 'disliked'}): {safe_pattern}"[:200]
        exp = self.record(
            agent="learner",
            task="user feedback",
            input_data=payload,
            output={"summary": feedback_summary},
            outcome="partial",
            user_feedback="liked" if liked else "disliked",
            tags=["user-feedback"],
        )
        return {"recorded": True, "experience_id": exp.experience_id}

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
