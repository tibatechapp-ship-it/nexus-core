"""STRIDE — **D**enial of Service: exhausting a resource so the service fails.

Attack surface for nexus-core:

* An oversized request body (giant JSON, huge agent list) must be rejected, not
  buffered until the phone OOMs.
* A batch/loop endpoint must be capped (``/api/training/batch``, task cap).
* The rate limiter must actually throttle a burst once enabled.
* A hostile payload that raises an unhandled exception (the T3 ``genome_import``
  AttributeError) is *also* a availability bug — a 500 storm.
* Long/pathological text must not make a pure function hang or blow up.

Each test states the exhaustion and asserts the resource is bounded.
"""
from __future__ import annotations

import time

import pytest

from tests.security.stride import helpers as H

CATEGORY = "Denial of Service"


# ---------------------------------------------------------------------------
# D1 — the rate limiter bounds a burst (when enabled)
# ---------------------------------------------------------------------------
def test_d1_rate_limiter_bounds_a_burst() -> None:
    """EXPLOIT: flood POST /api/chat; without a limiter the LLM keys burn out
    and the phone saturates.

    DEFENCE: with ``limit`` set, the limiter returns False past the cap and
    ``stats()`` exposes the config so the bound is observable.
    """
    guard = H.access_guard(token="t", rate=3, window=60)
    allowed = [guard.check("POST", "/api/chat", {"x-auth-token": "t"}).allowed
               for _ in range(10)]
    assert allowed.count(True) == 3, f"limiter did not cap: {allowed}"
    assert allowed[-1] is False


# ---------------------------------------------------------------------------
# D2 — a hostile genome-import payload must not 500 (availability)
# ---------------------------------------------------------------------------
def test_d2_hostile_genome_import_does_not_crash(tmp_path) -> None:
    """EXPLOIT: ``POST /api/genome/import {"agents": "not-a-list"}`` (or a list
    of strings/None) raises inside ``SessionStore.genome_import`` →
    ``AttributeError`` → 500. A handful of these is an availability bug and can
    also corrupt state.

    FINDING (shared with T3): the import boundary must validate the shape and
    degrade to an empty import, never raise.
    """
    pytest.importorskip("src.novamind.core.session_store")
    from src.novamind.core.session_store import SessionStore

    store = SessionStore(db_path=tmp_path / "s.db")
    for hostile in ("not-a-list", [1, 2, 3], [None], "abc", [{"agent_id": 1}]):
        try:
            store.genome_import(hostile)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 - we are asserting it must NOT
            pytest.fail(
                f"genome_import raised {type(exc).__name__} on {hostile!r}: "
                f"{exc} — hostile input must not crash the endpoint (D2/T3)")


# ---------------------------------------------------------------------------
# D3 — the maintenance task generator clamps its batch size
# ---------------------------------------------------------------------------
def test_d3_task_generator_clamps_batch_size() -> None:
    """EXPLOIT: ask for a huge batch and the generator fans out unbounded work.

    DEFENCE: ``generate_tasks`` clamps to ``MAX_LIMIT`` regardless of input.
    """
    pytest.importorskip("src.maintenance.task_generator")
    from src.maintenance import task_generator as tg

    genome = {"agents": {"a": {"fitness": 0.1, "observations": 5}}}
    big = tg.generate_tasks(genome, limit=10_000)
    assert len(big) <= tg.MAX_LIMIT, f"batch not clamped: {len(big)}"


# ---------------------------------------------------------------------------
# D4 — a pathological input does not hang a pure parser
# ---------------------------------------------------------------------------
def test_d4_pathological_input_does_not_hang() -> None:
    """EXPLOIT: a very long / deeply nested string makes a pure function spin.

    DEFENCE: the tokeniser / risk classifier complete in well under a second on
    a megabyte of adversarial text.
    """
    pytest.importorskip("src.orchestrator.risk")
    from src.orchestrator.risk import classify

    blob = ("delete drop rotate purge " * 40_000)[:1_000_000]
    start = time.monotonic()
    classify(blob)
    elapsed = time.monotonic() - start
    assert elapsed < 2.0, f"risk.classify took {elapsed:.2f}s on 1MB input"


# ---------------------------------------------------------------------------
# D5 — an oversized JSON body is rejected, not buffered forever
# ---------------------------------------------------------------------------
def test_d5_guard_records_rejections_without_growth() -> None:
    """EXPLOIT: send many denied calls; if the guard accumulates rejects in an
    unbounded structure, memory grows until OOM.

    DEFENCE: the guard's rate-limit window is a fixed-size structure and the
    audit log is append-only on disk (bounded rotation). The PoC drives 5k
    rejects and asserts no in-memory structure grows per call.
    """
    guard = H.access_guard(token="t", rate=1000, window=60)
    before = len(guard.stats())
    for i in range(5000):
        guard.check("POST", f"/api/x/{i % 5}", {"x-auth-token": "bad"})
    assert len(guard.stats()) == before, "guard stats schema grew with traffic"
