"""Compatibility facade for the canonical NovaMind factory pipeline.

Pipeline definitions, context handling, execution, summaries and formatting
are implemented only in :mod:`novamind.factory.pipeline`. This module keeps
the historical hive import path stable.
"""
from novamind.factory.pipeline import (
    PIPELINES,
    PipelineContext,
    format_result,
    list_pipelines,
    run_pipeline,
    run_pipeline_sync,
)

# Historical callers used both names for the same pipeline runner.
run_factory = run_pipeline

__all__ = [
    "PIPELINES",
    "PipelineContext",
    "run_pipeline",
    "run_pipeline_sync",
    "run_factory",
    "list_pipelines",
    "format_result",
]
