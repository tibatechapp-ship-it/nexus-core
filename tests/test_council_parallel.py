"""Phase 3.2 — council rounds must run their members concurrently.

Within a round the members are independent: each speaks once and the consensus
is computed only AFTER every member has replied.  Today the round loop awaits
each member's live reply in sequence, so a 6-member round costs the SUM of the
latencies.  The fix fans the members out concurrently and still yields the
stream in the original member order.

Proof of mechanism = the WALL-CLOCK of a round against a router whose replies
each sleep ``LATENCY``.  Serial ⇒ ≈ ``members * LATENCY``; parallel ⇒ ≈
``LATENCY``.  A generous margin keeps it stable on a loaded phone while still
failing loudly if the loop stays serial.
"""

from __future__ import annotations

import time

from src.novamind.council.council import Council, CouncilMember

LATENCY = 0.25


class _SlowRouter:
    """A live-looking router whose every reply takes ``LATENCY`` seconds."""

    def __init__(self) -> None:
        self.providers = [type("P", (), {"api_key": "live-key", "enabled": True})()]

    def generate(self, prompt, system="", role="fast", temperature=0.6, **kw):  # noqa: ANN001, ANN003
        time.sleep(LATENCY)
        return {"ok": True, "text": "opinion", "provider": "slow", "elapsed": LATENCY}


def _members(n: int) -> list[CouncilMember]:
    return [CouncilMember(id=f"m{i}", name=f"M{i}", emoji="🦉", system="s")
            for i in range(n)]


def _consume(gen) -> list[dict]:  # noqa: ANN001
    return list(gen)


def test_round_runs_members_concurrently() -> None:
    n = 6
    council = Council(router=_SlowRouter(), members=_members(n))
    start = time.monotonic()
    events = _consume(council.debate_stream("topic", rounds=1))
    elapsed = time.monotonic() - start

    assert len(events) >= n, "every member must still emit an event"
    serial = n * LATENCY
    # parallel should be near one latency; allow a full extra latency of slack
    assert elapsed < serial * 0.6, (
        f"round took {elapsed:.2f}s for {n} members at {LATENCY}s each "
        f"(serial ≈ {serial:.2f}s) — members are still awaited in sequence"
    )


def test_stream_still_emits_members_in_order() -> None:
    """Contract guard: parallelism must not reorder the stream."""
    council = Council(router=_SlowRouter(), members=_members(4))
    events = _consume(council.debate_stream("topic", rounds=1))
    order = [e["agent"] for e in events if e["type"] == "member_message"]
    assert order == ["m0", "m1", "m2", "m3"]
