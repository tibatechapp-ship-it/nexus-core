"""Observability configuration — Pydantic Settings."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ObservabilityConfig(BaseSettings):
    """NovaMind observability configuration."""

    model_config = SettingsConfigDict(
        env_prefix="NOVAMIND_OBS_",
        env_file=".env",
        extra="ignore",
    )

    # ═══ Tracing ═══
    tracing_enabled: bool = Field(
        default=True,
        description="Enable OpenTelemetry tracing.",
    )
    service_name: str = Field(
        default="novamind",
        description="Service name for traces.",
    )
    service_version: str = Field(
        default="3.3.0",
        description="Service version.",
    )

    # ═══ Exporter ═══
    exporter: str = Field(
        default="console",
        description="Trace exporter: 'console' | 'otlp' | 'none'.",
    )
    otlp_endpoint: str = Field(
        default="http://localhost:4317",
        description="OTLP gRPC endpoint.",
    )

    # ═══ Metrics ═══
    metrics_enabled: bool = Field(
        default=True,
        description="Enable Prometheus metrics.",
    )
    metrics_port: int = Field(
        default=9090,
        description="Prometheus HTTP port.",
    )

    # ═══ Cost tracking ═══
    cost_tracking_enabled: bool = Field(
        default=True,
        description="Track LLM costs in USD.",
    )

    # ═══ Sampling ═══
    sample_rate: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Trace sampling rate (0.0–1.0).",
    )


# Singleton
_config: ObservabilityConfig | None = None


def get_config() -> ObservabilityConfig:
    """Get or create global config."""
    global _config
    if _config is None:
        _config = ObservabilityConfig()
    return _config


def reset_config() -> None:
    """Reset config (for tests)."""
    global _config
    _config = None


__all__ = ["ObservabilityConfig", "get_config", "reset_config"]
