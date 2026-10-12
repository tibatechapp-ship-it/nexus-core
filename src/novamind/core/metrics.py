"""Prometheus Metrics - Observability."""
import logging
from typing import Optional

try:
    from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
    PROM_AVAILABLE = True
except ImportError:
    PROM_AVAILABLE = False

logger = logging.getLogger("Metrics")


# ═══════════════════════════════════════════
#  Global Metrics
# ═══════════════════════════════════════════
if PROM_AVAILABLE:
    # Missions
    missions_total = Counter(
        "novamind_missions_total",
        "Total missions",
        ["specialty", "status"]
    )
    mission_duration = Histogram(
        "novamind_mission_duration_seconds",
        "Mission duration",
        ["specialty"],
        buckets=[1, 5, 10, 20, 30, 60, 120, 300]
    )
    
    # Soldiers
    active_soldiers = Gauge(
        "novamind_active_soldiers",
        "Active soldiers"
    )
    soldiers_trust = Gauge(
        "novamind_soldiers_trust_avg",
        "Average trust score"
    )
    
    # LLM
    llm_calls = Counter(
        "novamind_llm_calls_total",
        "LLM calls",
        ["provider", "status"]
    )
    llm_duration = Histogram(
        "novamind_llm_duration_seconds",
        "LLM call duration",
        ["provider"]
    )
    llm_tokens = Counter(
        "novamind_llm_tokens_total",
        "LLM tokens used",
        ["provider", "direction"]
    )
    
    # Errors
    errors_total = Counter(
        "novamind_errors_total",
        "Total errors",
        ["component", "type"]
    )
    
    # Learning
    vaccines_total = Counter(
        "novamind_vaccines_total",
        "Vaccines produced",
        ["specialty"]
    )
    genome_genes = Gauge(
        "novamind_genome_genes_total",
        "Total genes"
    )


def record_mission(specialty: str, status: str, duration: float):
    if not PROM_AVAILABLE: return
    missions_total.labels(specialty=specialty, status=status).inc()
    mission_duration.labels(specialty=specialty).observe(duration)


def record_llm_call(provider: str, success: bool, duration: float, tokens_in: int = 0, tokens_out: int = 0):
    if not PROM_AVAILABLE: return
    status = "success" if success else "error"
    llm_calls.labels(provider=provider, status=status).inc()
    llm_duration.labels(provider=provider).observe(duration)
    if tokens_in:
        llm_tokens.labels(provider=provider, direction="in").inc(tokens_in)
    if tokens_out:
        llm_tokens.labels(provider=provider, direction="out").inc(tokens_out)


def update_company_metrics(supreme):
    if not PROM_AVAILABLE: return
    active_soldiers.set(len(supreme.soldiers))
    if supreme.soldiers:
        avg_trust = sum(s.stats.trust_score for s in supreme.soldiers) / len(supreme.soldiers)
        soldiers_trust.set(avg_trust)
    genome_genes.set(supreme.genome.stats().get("total_genes", 0))


def get_metrics() -> bytes:
    if not PROM_AVAILABLE:
        return b"# prometheus_client not installed"
    return generate_latest()


def get_content_type() -> str:
    if not PROM_AVAILABLE:
        return "text/plain"
    return CONTENT_TYPE_LATEST


def is_available() -> bool:
    return PROM_AVAILABLE
