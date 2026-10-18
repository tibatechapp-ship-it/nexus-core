"""The agent learning package.

Phase 1 + 1.5 — :class:`ExperienceCollector`: a thread-safe in-memory buffer
that records what each agent did and how it ended (:class:`Experience` /
:class:`Outcome`) — newest-first queries, statistics, JSON/JSONL export/import,
retention pruning and fail-safe recording against the canonical
:data:`KNOWN_AGENT_ROLES` / :data:`KNOWN_ACTION_TYPES`.

Phase 2 — :class:`LessonExtractor`: distils those experiences into reusable
:class:`Lesson` principles (via a :class:`~src.core.backend.LLMBackend`),
merging similar ones and scoring confidence.

Phase 2 (Tool Use) — the tool library in :mod:`src.learning.tools`:
``search_web`` / ``read_file`` / ``get_current_time`` / ``query_memory`` /
``execute_code`` behind a config-gated :func:`~src.learning.tools.safe_execute`
that never raises and always returns a :class:`~src.learning.tools.ToolResult`
carrying an ``explain`` line.  Day 2 adds :class:`~src.learning.react_agent.
ReActAgent`, a Thought→Action→Observation→Answer loop driven by an injectable
think callable.

Phase 3 — :class:`LessonStore` + :class:`LessonInjector`: rank the stored
lessons against a task and fold the relevant ones into an agent's prompt
(:func:`render_lessons`), closing the learn → apply loop.

Phase 4 — :class:`LearningOrchestrator` runs the whole pipeline
(collector → extractor → store) in one call and drops weak lessons, while
:class:`LessonDatabase` persists lessons to SQLite.

Phase 5 — :class:`ContinualLearningManager` coordinates the full learning loop
(collect → extract → validate → merge) and can run it automatically
(:meth:`~ContinualLearningManager.schedule` + :meth:`~ContinualLearningManager.run_due`),
merging recurring lessons into existing store entries instead of duplicating.
"""

from __future__ import annotations

from src.learning.anti_forgetting import (
    AntiForgetting,
    Conflict,
    ConsolidationResult,
    polarity,
)
from src.learning.experience_collector import (
    DAY,
    KNOWN_ACTION_TYPES,
    KNOWN_AGENT_ROLES,
    Experience,
    ExperienceCollector,
    Outcome,
)
from src.learning.interactions import (
    InteractionStore,
    default_interaction_db_path,
    get_interaction_store,
    reset_interaction_store,
)
from src.learning.lesson import Lesson, LessonExtractor
from src.learning.reflection import (
    RATINGS,
    awareness_gap,
    build_reflection_prompt,
    build_retry_system,
    memory_block,
    parse_reflection,
    rating_score,
    should_retry,
)
from src.learning.lesson_store import (
    LessonDatabase,
    LessonInjector,
    LessonStore,
    default_lesson_db_path,
    render_lessons,
)
from src.learning.manager import (
    ContinualLearningManager,
    LearningCycle,
    LessonValidator,
    SchedulePolicy,
)
from src.learning.orchestrator import (
    DEFAULT_MIN_CONFIDENCE,
    ExtractionReport,
    LearningOrchestrator,
)
from src.learning.react_agent import (
    MAX_STEPS_DEFAULT,
    ReActAgent,
    ReActResult,
    parse_action,
)
from src.learning.tools import (
    ToolResult,
    ToolsConfigError,
    default_config,
    get_current_time,
    is_safe_path,
    list_tools,
    load_tools_config,
    query_memory,
    read_file,
    safe_execute,
    save_tools_config,
    search_web,
    tool_explain,
)

__all__ = [
    "DAY",
    "DEFAULT_MIN_CONFIDENCE",
    "KNOWN_ACTION_TYPES",
    "KNOWN_AGENT_ROLES",
    "AntiForgetting",
    "Conflict",
    "ConsolidationResult",
    "ContinualLearningManager",
    "Experience",
    "ExperienceCollector",
    "ExtractionReport",
    "Lesson",
    "LessonDatabase",
    "LessonExtractor",
    "LessonInjector",
    "LessonStore",
    "LessonValidator",
    "LearningCycle",
    "LearningOrchestrator",
    "MAX_STEPS_DEFAULT",
    "Outcome",
    "RATINGS",
    "ReActAgent",
    "ReActResult",
    "SchedulePolicy",
    "InteractionStore",
    "ToolResult",
    "ToolsConfigError",
    "awareness_gap",
    "build_reflection_prompt",
    "build_retry_system",
    "default_config",
    "default_interaction_db_path",
    "default_lesson_db_path",
    "get_current_time",
    "get_interaction_store",
    "is_safe_path",
    "list_tools",
    "load_tools_config",
    "memory_block",
    "parse_action",
    "parse_reflection",
    "polarity",
    "query_memory",
    "rating_score",
    "read_file",
    "render_lessons",
    "reset_interaction_store",
    "safe_execute",
    "save_tools_config",
    "search_web",
    "should_retry",
    "tool_explain",
]