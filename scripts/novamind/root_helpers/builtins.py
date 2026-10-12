"""
Built-in hooks - Auto-registered on import
- 7 ready-to-use hooks
- Connects memory to agent events
- Session summaries
"""
from pathlib import Path
import sys
import logging
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hooks.manager import hooks
from core.semantic import semantic_memory

logger = logging.getLogger("hooks.builtins")

# Session state
_session_started_at = None
_session_lessons = []
_session_errors = []


# -----------------------------------------------------------
# 1. session:start - beginning of a session
# -----------------------------------------------------------
def on_session_start(ctx):
    global _session_started_at, _session_lessons, _session_errors
    _session_started_at = datetime.now(timezone.utc).timestamp()
    _session_lessons = []
    _session_errors = []
    logger.info("[session] started")


hooks.register("session:start", on_session_start)


# -----------------------------------------------------------
# 2. session:end - save accumulated lessons
# -----------------------------------------------------------
def on_session_end(ctx):
    global _session_started_at, _session_lessons, _session_errors

    if _session_started_at is None:
        return

    duration = datetime.now(timezone.utc).timestamp() - _session_started_at

    # Save each lesson from this session
    saved_count = 0
    for lesson in _session_lessons:
        try:
            semantic_memory.append(
                text=lesson,
                source="session",
                confidence=0.8,
            )
            saved_count += 1
        except Exception as e:
            logger.warning("[session] failed to save lesson: " + str(e))

    # Log summary
    if saved_count > 0 or _session_errors:
        summary_parts = []
        summary_parts.append("dur=" + format(duration, ".1f") + "s")
        if saved_count > 0:
            summary_parts.append("lessons=" + str(saved_count))
        if _session_errors:
            summary_parts.append("errors=" + str(len(_session_errors)))
        logger.info("[session] ended: " + " ".join(summary_parts))

    _session_started_at = None
    _session_lessons = []
    _session_errors = []


hooks.register("session:end", on_session_end)


# -----------------------------------------------------------
# 3. fix:success - record a learned lesson
# -----------------------------------------------------------
def on_fix_success(ctx):
    global _session_lessons
    lesson = ctx.data.get("lesson") or ctx.data.get("pattern")
    if lesson:
        _session_lessons.append(str(lesson))
        logger.info("[fix] lesson queued: " + str(lesson)[:60])


hooks.register("fix:success", on_fix_success)


# -----------------------------------------------------------
# 4. fix:failed - record the failure
# -----------------------------------------------------------
def on_fix_failed(ctx):
    global _session_errors
    error = ctx.data.get("error")
    if error:
        _session_errors.append(str(error))


hooks.register("fix:failed", on_fix_failed)


# -----------------------------------------------------------
# 5. tool:error - log
# -----------------------------------------------------------
def on_tool_error(ctx):
    tool_name = ctx.data.get("toolName", "?")
    error = ctx.data.get("error", "?")
    logger.error("[tool:error] " + str(tool_name) + ": " + str(error)[:100])


hooks.register("tool:error", on_tool_error)


# -----------------------------------------------------------
# 6. memory:recall - log usage
# -----------------------------------------------------------
def on_memory_recall(ctx):
    count = ctx.data.get("count", 0)
    if count > 0:
        logger.debug("[memory:recall] " + str(count) + " lessons loaded")


hooks.register("memory:recall", on_memory_recall)


# -----------------------------------------------------------
# 7. memory:remember - block huge text
# -----------------------------------------------------------
def on_memory_remember(ctx):
    text = ctx.data.get("text", "")
    if text and len(str(text)) > 5000:
        ctx.cancel("text too large for memory (>5000 chars)")


hooks.register("memory:remember", on_memory_remember)


# -----------------------------------------------------------
# Export session lessons count (for testing)
# -----------------------------------------------------------
def get_session_stats():
    return {
        "started_at": _session_started_at,
        "lessons_count": len(_session_lessons),
        "errors_count": len(_session_errors),
    }


logger.info("[hooks.builtins] 7 built-in hooks registered")
