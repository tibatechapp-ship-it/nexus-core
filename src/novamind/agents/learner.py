"""
Learner Agent — durable feedback and explicit learning outcomes.
"""
import copy
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

logger = logging.getLogger("agents.learner")

from novamind.core.paths import NOVAMIND_HOME as BASE

FEEDBACK_FILE = BASE / "memory" / "feedback.json"


class LearnerAgent:
    """Persist user feedback and learning experiences without false acknowledgements."""

    def __init__(self):
        self.name = "learner"
        self.feedback = self._load_feedback()

    def _load_feedback(self) -> Dict:
        if FEEDBACK_FILE.exists():
            try:
                data = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
                if (
                    isinstance(data, dict)
                    and isinstance(data.get("entries"), list)
                    and isinstance(data.get("pattern_weights"), dict)
                ):
                    return data
                logger.warning("Ignoring malformed learner feedback structure")
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Could not load learner feedback: %s", exc)
        return {"entries": [], "pattern_weights": {}}

    def _save_feedback(self):
        """Atomically replace the feedback document after a durable temp-file write."""
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=FEEDBACK_FILE.parent,
                prefix=f".{FEEDBACK_FILE.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(self.feedback, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(temporary_path, FEEDBACK_FILE)
            temporary_path = None

            # Persist the directory entry on POSIX filesystems when supported.
            if hasattr(os, "O_DIRECTORY"):
                directory_fd = os.open(FEEDBACK_FILE.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    logger.exception("Could not remove temporary feedback file")

    def learn(
        self,
        summary: str,
        source: str = "session",
        min_confidence: float = 0.5,
    ) -> Dict:
        """Persist a session lesson in the append-only learning ledger.

        min_confidence is retained for API compatibility and validated, but
        no confidence score is fabricated when the caller supplies none.
        """
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("summary must be a non-empty string")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source must be a non-empty string")
        if isinstance(min_confidence, bool) or not isinstance(min_confidence, (int, float)):
            raise TypeError("min_confidence must be numeric")
        if not 0.0 <= float(min_confidence) <= 1.0:
            raise ValueError("min_confidence must be between 0 and 1")

        try:
            from novamind.core.learning_loop import learning_loop

            experience = learning_loop.record(
                agent="learner",
                task=f"Learn from {source.strip()[:100]}",
                input_data=summary.strip(),
                output={"summary": summary.strip()[:200]},
                outcome="success",
                tags=["session-learning"],
            )
            logger.info("learned session lesson: %s", summary[:100])
            return {
                "ok": True,
                "learned": 1,
                "experience_id": experience.experience_id,
            }
        except Exception as exc:
            logger.exception("Session learning failed")
            return {"ok": False, "error": str(exc)[:200]}

    def record_feedback(
        self,
        pattern: str,
        liked: bool,
        context: str = "",
        source: str = "user",
    ) -> Dict:
        """Persist primary feedback and explicitly report secondary-ledger status."""
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError("pattern must be a non-empty string")
        if not isinstance(liked, bool):
            raise TypeError("liked must be a boolean")
        if not isinstance(context, str):
            raise TypeError("context must be a string")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source must be a non-empty string")

        normalized_pattern = pattern.strip()
        entry = {
            "pattern": normalized_pattern,
            "liked": liked,
            "context": context[:200],
            "source": source.strip(),
            "at": datetime.now(timezone.utc).isoformat(),
        }

        previous_feedback = self.feedback
        candidate = copy.deepcopy(previous_feedback)
        candidate["entries"].append(entry)

        key = self._normalize_pattern(normalized_pattern)
        weight = candidate["pattern_weights"].setdefault(
            key, {"likes": 0, "dislikes": 0, "net": 0}
        )
        if liked:
            weight["likes"] += 1
            weight["net"] += 1
        else:
            weight["dislikes"] += 1
            weight["net"] -= 1

        self.feedback = candidate
        try:
            self._save_feedback()
        except Exception:
            self.feedback = previous_feedback
            logger.exception("Primary feedback persistence failed")
            raise

        learning_recorded = False
        warning = None
        experience_id = None
        try:
            from novamind.core.learning_loop import learning_loop

            result = learning_loop.record_feedback(normalized_pattern, liked)
            learning_recorded = bool(result.get("ok"))
            experience_id = result.get("experience_id")
            if not learning_recorded:
                warning = "Primary feedback saved, but the learning ledger did not acknowledge persistence."
        except Exception as exc:
            warning = (
                "Primary feedback saved, but secondary learning-ledger persistence failed: "
                + str(exc)[:160]
            )
            logger.exception("Secondary learning-ledger persistence failed")

        logger.info("feedback persisted for pattern: %s", normalized_pattern[:50])
        response = {
            "ok": True,
            "feedback_saved": True,
            "learning_recorded": learning_recorded,
            "entry": entry,
            "weight": dict(weight),
            "experience_id": experience_id,
        }
        if warning:
            response["warning"] = warning
        return response

    def get_pattern_weight(self, pattern: str) -> float:
        """Get weight for a pattern. Higher means more preferred."""
        key = self._normalize_pattern(pattern)
        weight = self.feedback["pattern_weights"].get(key, {})
        net = weight.get("net", 0)
        total = weight.get("likes", 0) + weight.get("dislikes", 0)
        if total == 0:
            return 0.5
        return max(0.0, min(1.0, (net + total) / (2 * total)))

    def should_suggest(self, pattern: str, threshold: float = 0.3) -> bool:
        """Return whether feedback supports suggesting this pattern."""
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise TypeError("threshold must be numeric")
        if not 0.0 <= float(threshold) <= 1.0:
            raise ValueError("threshold must be between 0 and 1")
        return self.get_pattern_weight(pattern) >= threshold

    def _normalize_pattern(self, pattern: str) -> str:
        """Normalize a pattern for stable matching."""
        import re

        normalized = pattern.lower()
        normalized = re.sub(r"line\\s+\\d+", "line", normalized)
        normalized = re.sub(r"[^\\w\\s]", "", normalized)
        return " ".join(normalized.split())[:100]

    def stats(self) -> Dict:
        """Return durable feedback statistics."""
        entries = self.feedback["entries"]
        weights = self.feedback["pattern_weights"]
        liked = sum(1 for entry in entries if entry["liked"])
        disliked = len(entries) - liked
        top_patterns = sorted(
            weights.items(),
            key=lambda item: -abs(item[1].get("net", 0)),
        )[:10]
        return {
            "total_feedback": len(entries),
            "liked": liked,
            "disliked": disliked,
            "like_rate": liked / len(entries) if entries else 0,
            "unique_patterns": len(weights),
            "top_patterns": [
                {"pattern": pattern, **weight}
                for pattern, weight in top_patterns
            ],
        }


learner_agent = LearnerAgent()
__all__ = ["LearnerAgent", "learner_agent"]
