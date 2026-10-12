"""Tests for the Living Council (v2.0 scaffold).

The council core is pure Python with a deterministic offline fallback, so these
tests run in the phone framework gate without any ``novamind`` extras and
without a network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.novamind.core.session_store import SessionStore
from src.novamind.council import (
    COUNCIL_MEMBERS,
    Council,
    CouncilMember,
    consensus,
    influence,
    jaccard,
    position,
)


@pytest.fixture()
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path / "sessions.db")


# ── pure helpers ─────────────────────────────────────────────────────────────
def test_jaccard_identical_is_one() -> None:
    assert jaccard("hello world", "hello world") == 1.0


def test_jaccard_disjoint_is_zero() -> None:
    assert jaccard("alpha beta", "gamma delta") == 0.0


def test_jaccard_empty_is_zero() -> None:
    assert jaccard("", "anything") == 0.0
    assert jaccard("anything", "") == 0.0


def test_jaccard_partial() -> None:
    score = jaccard("the quick brown fox", "the quick red fox")
    assert 0.0 < score < 1.0


def test_jaccard_handles_arabic() -> None:
    assert jaccard("القرار صحيح", "القرار صحيح") == 1.0


def test_position_extracts_stance_line() -> None:
    text = "كلام كثير هنا.\nالموقف: نعم أوافق على المقترح"
    assert position(text) == "نعم أوافق على المقترح"


def test_position_stance_english() -> None:
    assert position("blah\nSTANCE: go now") == "go now"


def test_position_falls_back_to_last_slice() -> None:
    assert position("no stance marker here") == "no stance marker here"


def test_consensus_unanimous() -> None:
    texts = ["الموقف: نفس الشيء"] * 5
    assert consensus(texts) == 1.0


def test_consensus_majority() -> None:
    texts = ["الموقف: نوافق", "الموقف: نوافق", "الموقف: مختلف تماما هنا"]
    assert consensus(texts) == pytest.approx(2 / 3)


def test_consensus_empty() -> None:
    assert consensus([]) == 0.0
    assert consensus(["", "   "]) == 0.0


def test_influence_ranks_against_verdict() -> None:
    members = [CouncilMember("a", "A", "🅰", "sys"), CouncilMember("b", "B", "🅱", "sys")]
    latest = {"a": "verdict text here", "b": "totally unrelated content"}
    inf = influence(members, latest, "verdict text here")
    assert set(inf) == {"a", "b"}
    assert inf["a"]["alignment"] > inf["b"]["alignment"]
    assert inf["a"]["standing_delta"] == 1
    assert inf["b"]["standing_delta"] == -1


def test_influence_empty_members() -> None:
    assert influence([], {"a": "x"}, "y") == {}


# ── offline debate ───────────────────────────────────────────────────────────
def test_debate_offline_produces_full_result() -> None:
    council = Council(router=None, store=None)
    result = council.debate("هل نبني الميزة الآن؟", rounds=3)
    assert result["topic"] == "هل نبني الميزة الآن؟"
    assert result["rounds"] == 3
    assert len(result["rounds_data"]) == 3
    assert result["offline"] is True
    assert result["verdict"]
    assert 0.0 <= result["consensus"] <= 1.0
    assert set(result["influence"]) == {m.id for m in COUNCIL_MEMBERS}


def test_debate_stream_event_order() -> None:
    council = Council(router=None, store=None)
    events = list(council.debate_stream("موضوع", rounds=2))
    types = [e["type"] for e in events]
    assert types[0] == "session"
    assert types[-1] == "done"
    assert "verdict" in types
    assert types.count("round") == 2
    # every round emits one member_message per council member
    msgs = [e for e in events if e["type"] == "member_message"]
    assert len(msgs) == 2 * len(COUNCIL_MEMBERS)
    # consensus is announced after each round
    assert types.count("consensus") == 2


def test_debate_empty_topic_gets_default() -> None:
    council = Council(router=None, store=None)
    result = council.debate("   ", rounds=1)
    assert result["topic"] == "موضوع غير محدّد"


@pytest.mark.parametrize("rounds,expected", [(0, 1), (1, 1), (3, 3), (9, 5)])
def test_rounds_clamped(rounds: int, expected: int) -> None:
    council = Council(router=None, store=None)
    result = council.debate("t", rounds=rounds)
    assert result["rounds"] == expected
    assert len(result["rounds_data"]) == expected


def test_session_event_lists_members() -> None:
    council = Council(router=None, store=None)
    events = list(council.debate_stream("t", rounds=1))
    session = events[0]
    assert len(session["members"]) == len(COUNCIL_MEMBERS)
    assert {"id", "name", "emoji"} <= set(session["members"][0])


def test_custom_members_subset() -> None:
    two = COUNCIL_MEMBERS[:2]
    council = Council(router=None, store=None, members=two)
    result = council.debate("t", rounds=1)
    assert [m["id"] for m in result["members"]] == [m.id for m in two]


# ── persistence ──────────────────────────────────────────────────────────────
def test_debate_persists_session_and_messages(store: SessionStore) -> None:
    council = Council(router=None, store=store)
    result = council.debate("موضوع محفوظ", rounds=2)
    sid = result["session_id"]
    assert sid

    session = store.get_council_session(sid)
    assert session is not None
    assert session["topic"] == "موضوع محفوظ"
    assert session["status"] == "done"
    assert session["verdict"]
    assert len(session["messages"]) == 2 * len(COUNCIL_MEMBERS)
    assert session["meta"]["members"][0]["id"] == COUNCIL_MEMBERS[0].id


def test_list_and_delete_council_sessions(store: SessionStore) -> None:
    council = Council(router=None, store=store)
    council.debate("one", rounds=1)
    council.debate("two", rounds=1)

    sessions = store.list_council_sessions()
    assert len(sessions) == 2
    assert {"one", "two"} == {s["topic"] for s in sessions}

    sid = sessions[0]["id"]
    assert store.delete_council_session(sid) is True
    assert store.get_council_session(sid) is None
    assert len(store.list_council_sessions()) == 1


def test_list_council_messages(store: SessionStore) -> None:
    council = Council(router=None, store=store)
    result = council.debate("m", rounds=1)
    msgs = store.list_council_messages(result["session_id"])
    assert len(msgs) == len(COUNCIL_MEMBERS)
    assert all("meta" in m for m in msgs)


def test_delete_missing_council_session(store: SessionStore) -> None:
    assert store.delete_council_session("nope") is False


def test_stats_counts_council(store: SessionStore) -> None:
    council = Council(router=None, store=store)
    council.debate("s", rounds=1)
    stats = store.stats()
    assert stats["council_sessions"] == 1
    assert stats["council_messages"] == len(COUNCIL_MEMBERS)
