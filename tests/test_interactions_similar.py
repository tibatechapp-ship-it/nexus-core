"""Phase 3.1 — ``similar()`` must not scan the whole table.

The store can hold tens of thousands of interactions; ``similar()`` runs on the
hot path of every ``/api/chat``.  The fix caps the candidate window (a bounded
``ORDER BY created_at DESC`` sub-selection) and adds an index for it.

The assertion counts ROWS READ (via the ``_rows`` seam), not wall-clock — a
timing assertion is flaky on a loaded phone and would not prove the mechanism.
"""

from __future__ import annotations

from src.learning.interactions import InteractionStore

WINDOW_CAP = 500


def _seed(store: InteractionStore, n_old: int, n_recent: int, clock) -> None:  # noqa: ANN001
    """Insert ``n_old`` irrelevant rows (older), then ``n_recent`` matches (newer)."""
    for i in range(n_old):
        clock.now += 1.0
        store.save(
            agent_id="coder",
            question=f"unrelated legacy question number {i}",
            answer=f"answer {i}",
            signal_ok=True,
        )
    for i in range(n_recent):
        clock.now += 1.0
        store.save(
            agent_id="coder",
            question=f"add a retry flag to the parser {i}",
            answer=f"recent answer {i}",
            signal_ok=True,
        )


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def test_similar_does_not_read_the_whole_table(tmp_path) -> None:
    clock = _Clock()
    store = InteractionStore(str(tmp_path / "i.db"), clock=clock)
    total = 1000
    _seed(store, n_old=total, n_recent=5, clock=clock)

    rows_read: list[int] = []
    real_rows = store._rows

    def counting_rows(sql, params=()):  # noqa: ANN001, ANN202 - test seam
        out = real_rows(sql, params)
        rows_read.append(len(out))
        return out

    store._rows = counting_rows  # type: ignore[method-assign]
    try:
        results = store.similar("add a retry flag to the parser", k=5)
    finally:
        store._rows = real_rows  # type: ignore[method-assign]

    assert results, "the 5 matching rows must be found"
    scanned = sum(rows_read)
    assert scanned <= WINDOW_CAP, (
        f"similar() read {scanned} rows (whole table = {total + 5}) — "
        f"the window cap is not applied"
    )


def test_similar_still_ranks_and_limits(tmp_path) -> None:
    """Behaviour guard: capping the window must not break ranking / k."""
    clock = _Clock()
    store = InteractionStore(str(tmp_path / "i.db"), clock=clock)
    _seed(store, n_old=50, n_recent=5, clock=clock)
    results = store.similar("add a retry flag to the parser", k=3)
    assert len(results) == 3
    assert all(r["score"] > 0 for r in results)
    # newest-first among equals: the last seeded row is the most recent match
    assert results[0]["answer"] == "recent answer 4"


def test_similar_empty_query_returns_empty(tmp_path) -> None:
    clock = _Clock()
    store = InteractionStore(str(tmp_path / "i.db"), clock=clock)
    _seed(store, n_old=10, n_recent=2, clock=clock)
    assert store.similar("   ...   ") == []
