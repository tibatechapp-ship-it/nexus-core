"""Agent training pipeline (P3) + field loop (P4).

Wires the pre-existing, previously-unwired training stack into a live service:

* :mod:`.models` — immutable run record + the graduation floor.
* :mod:`.store`  — SQLite persistence for runs and certificates.
* :mod:`.engine` — deterministic trainer that decides graduation and certifies.
* :mod:`.field`  — the closed loop: run → lesson → genome → evolution.
* :mod:`.api`    — the ``/api/training/*`` HTTP surface (needs FastAPI).

Imported by the gateway; the pure layers (models/store/engine) work on a bare
phone install with no optional dependencies.
"""
from __future__ import annotations

import logging

from .engine import (
    CRITICAL_FAILURE_BELOW,
    DEFAULT_MODULE_MIN_SCORE,
    ModuleSpec,
    TrainingEngine,
    deterministic_evaluator,
    get_engine,
    normalize_tag,
    reset_engine,
    reset_signer,
)
from .field import (
    FIELD_ENV,
    LESSON_DB_ENV,
    FieldLoop,
    default_lesson_db_path,
    field_enabled,
    get_field_loop,
    lesson_from_run,
    reset_field_loop,
)
from .models import (
    GRADUATION_MIN_SCORE,
    RETRAIN_FLOOR,
    TrainingRun,
    TrainingVerdict,
    verdict_for,
)
from .store import (
    SCHEMA_VERSION,
    TrainingStore,
    default_db_path,
    get_store,
    reset_store,
)

# Library code should not configure logging; the app decides.  A NullHandler
# keeps ``import`` silent for embedders while still allowing ``setLevel``.
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "GRADUATION_MIN_SCORE",
    "RETRAIN_FLOOR",
    "CRITICAL_FAILURE_BELOW",
    "DEFAULT_MODULE_MIN_SCORE",
    "ModuleSpec",
    "SCHEMA_VERSION",
    "TrainingRun",
    "TrainingVerdict",
    "TrainingStore",
    "TrainingEngine",
    "verdict_for",
    "default_db_path",
    "deterministic_evaluator",
    "normalize_tag",
    "get_store",
    "reset_store",
    "get_engine",
    "reset_engine",
    "reset_signer",
    "FieldLoop",
    "FIELD_ENV",
    "LESSON_DB_ENV",
    "default_lesson_db_path",
    "field_enabled",
    "get_field_loop",
    "lesson_from_run",
    "reset_field_loop",
]
