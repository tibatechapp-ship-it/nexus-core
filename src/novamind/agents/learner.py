"""
Learner Agent v2 — With feedback loop and weight adjustment.
"""
import logging
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("agents.learner")

from novamind.core.paths import NOVAMIND_HOME as BASE
FEEDBACK_FILE = BASE / "memory" / "feedback.json"


class LearnerAgent:
    """Learns from feedback and improves over time."""

    def __init__(self):
        self.name = "learner"
        self.feedback = self._load_feedback()

    def _load_feedback(self) -> Dict:
        if FEEDBACK_FILE.exists():
            try:
                return json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"entries": [], "pattern_weights": {}}

    def _save_feedback(self):
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        FEEDBACK_FILE.write_text(
            json.dumps(self.feedback, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def learn(self, summary: str, source: str = "session",
              min_confidence: float = 0.5) -> Dict:
        """Persist a sanitized session lesson through the canonical loop."""
        try:
            from novamind.core.learning_loop import (
                _redact_learning_text,
                learning_loop,
            )

            if not isinstance(summary, str) or not summary.strip():
                return {"ok": False, "error": "summary must be a non-empty string"}
            if isinstance(min_confidence, bool) or not 0.0 <= min_confidence <= 1.0:
                return {"ok": False, "error": "min_confidence must be between 0 and 1"}
            if not isinstance(source, str) or not source.strip():
                return {"ok": False, "error": "source must be a non-empty string"}

            safe_summary = _redact_learning_text(summary.strip())[:180]
            experience = learning_loop.record(
                agent="learner",
                task="session_learning",
                input_data=summary,
                output={"summary": safe_summary},
                outcome="partial",
                user_feedback=f"source:{source[:80]}",
                tags=["session", source[:80], f"confidence:{min_confidence:.2f}"],
            )
            logger.info("learned: %s", safe_summary[:100])
            return {"ok": True, "experience": experience.to_dict()}
        except Exception as exc:
            safe_error = _redact_learning_text(str(exc))[:200]
            logger.error("learn failed: %s", safe_error)
            return {"ok": False, "error": safe_error}

    # ═══════════════════════════════════════════════════════
    # Feedback Loop (NEW)
    # ═══════════════════════════════════════════════════════
    def record_feedback(self, pattern: str, liked: bool,
                        context: str = "", source: str = "user") -> Dict:
        """Save sanitized local feedback and expose central-loop status."""
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError("pattern must be a non-empty string")
        if not isinstance(liked, bool):
            raise ValueError("liked must be a boolean")

        from novamind.core.learning_loop import (
            _redact_learning_text,
            learning_loop,
        )

        safe_pattern = _redact_learning_text(pattern)[:200]
        safe_context = _redact_learning_text(context)[:200]
        safe_source = _redact_learning_text(source)[:80]
        entry = {
            "pattern": safe_pattern,
            "liked": liked,
            "context": safe_context,
            "source": safe_source,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        self.feedback["entries"].append(entry)

        key = self._normalize_pattern(safe_pattern)
        if key not in self.feedback["pattern_weights"]:
            self.feedback["pattern_weights"][key] = {
                "likes": 0, "dislikes": 0, "net": 0,
            }
        weight = self.feedback["pattern_weights"][key]
        if liked:
            weight["likes"] += 1
            weight["net"] += 1
        else:
            weight["dislikes"] += 1
            weight["net"] -= 1

        self._save_feedback()

        learning_recorded = False
        warning = ""
        try:
            learning_loop.record_feedback(
                safe_pattern, liked, context=safe_context, source=safe_source
            )
            learning_recorded = True
        except Exception as exc:
            warning = _redact_learning_text(
                f"{type(exc).__name__}: {exc}"
            )[:200]
            logger.warning("feedback saved locally; central learning failed: %s", warning)

        result = {
            "ok": True,
            "feedback_saved": True,
            "learning_recorded": learning_recorded,
            "entry": entry,
            "weight": weight,
        }
        if warning:
            result["warning"] = warning
        return result

    def get_pattern_weight(self, pattern: str) -> float:
        """Get weight for a pattern. Higher = more preferred."""
        key = self._normalize_pattern(pattern)
        w = self.feedback["pattern_weights"].get(key, {})
        net = w.get("net", 0)
        total = w.get("likes", 0) + w.get("dislikes", 0)
        if total == 0:
            return 0.5  # neutral
        # Normalize to 0-1
        return max(0.0, min(1.0, (net + total) / (2 * total)))

    def should_suggest(self, pattern: str, threshold: float = 0.3) -> bool:
        """Should we suggest this pattern? Based on feedback weight."""
        return self.get_pattern_weight(pattern) >= threshold

    def _normalize_pattern(self, pattern: str) -> str:
        """Normalize pattern for matching."""
        import re
        p = pattern.lower()
        p = re.sub(r'line\s+\d+', 'line', p)
        p = re.sub(r'[^\w\s]', '', p)
        p = ' '.join(p.split())
        return p[:100]

    def stats(self) -> Dict:
        """Return learning stats."""
        entries = self.feedback["entries"]
        weights = self.feedback["pattern_weights"]

        liked = sum(1 for e in entries if e["liked"])
        disliked = len(entries) - liked

        top_patterns = sorted(
            weights.items(),
            key=lambda x: -abs(x[1].get("net", 0)),
        )[:10]

        return {
            "total_feedback": len(entries),
            "liked": liked,
            "disliked": disliked,
            "like_rate": liked / len(entries) if entries else 0,
            "unique_patterns": len(weights),
            "top_patterns": [
                {"pattern": p, **w}
                for p, w in top_patterns
            ],
        }


# Export
learner_agent = LearnerAgent()
__all__ = ["LearnerAgent", "learner_agent"]
