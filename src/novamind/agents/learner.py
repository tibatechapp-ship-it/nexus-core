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
        """Learn from a session summary."""
        try:
            from novamind.core.learning_loop import learning_loop

            # Add lesson
            lessons = [{"description": summary, "severity": "info"}]
            result = learning_loop.learn_from_pr_review(
                repo=source, pr_num=0, issues=lessons,
            )

            logger.info(f"learned: {summary[:100]}")
            return {"ok": True, **result}
        except Exception as e:
            logger.error(f"learn failed: {e}")
            return {"ok": False, "error": str(e)[:200]}

    # ═══════════════════════════════════════════════════════
    # Feedback Loop (NEW)
    # ═══════════════════════════════════════════════════════
    def record_feedback(self, pattern: str, liked: bool,
                        context: str = "", source: str = "user") -> Dict:
        """
        Record user feedback on a suggestion.
        - liked: True (👍) or False (👎)
        """
        entry = {
            "pattern": pattern,
            "liked": liked,
            "context": context[:200],
            "source": source,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        self.feedback["entries"].append(entry)

        # Update weights
        key = self._normalize_pattern(pattern)
        if key not in self.feedback["pattern_weights"]:
            self.feedback["pattern_weights"][key] = {"likes": 0, "dislikes": 0, "net": 0}

        w = self.feedback["pattern_weights"][key]
        if liked:
            w["likes"] += 1
            w["net"] += 1
        else:
            w["dislikes"] += 1
            w["net"] -= 1

        self._save_feedback()

        # Also update learning_loop if available
        try:
            from novamind.core.learning_loop import learning_loop
            learning_loop.record_feedback(pattern, liked)
        except Exception:
            pass

        logger.info(f"feedback: {pattern[:50]} → {'👍' if liked else '👎'}")
        return {"ok": True, "entry": entry, "weight": w}

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
