"""اختبارات خط التذاكر — من تذكرة إلى فرع مُبلَّغ.

العقد المفحوص: تذكرة بلا معايير تُرفض، اسم فرع آمن ومقيَّد، التنفيذ عبر
محرك مُمرَّر، فشل معيار واحد يحجب، بلا محرك حالة معلنة، تقرير حتمي يُكتب،
وتتبع صادق يُسجَّل — والخط لا يهدم أبداً بعطل المحرك.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.orchestrator.tickets import (
    MAX_BRANCH_LENGTH, PRIORITIES, STATUSES, Ticket, TicketResult,
    TicketRunner, branch_for,
)


class EngineOk:
    """محرك مثالي: يخطط وينجح كل معيار."""

    def __init__(self, steps: list[str] | None = None):
        self.steps = steps or ["خطوة أولى", "خطوة ثانية"]

    def plan(self, goal: str) -> list[str]:
        return self.steps

    def check(self, criterion: str, plan: list[str]) -> bool:
        return True


class EnginePartial:
    """محرك يعجز عن معيار واحد محدد."""

    def plan(self, goal: str) -> list[str]:
        return ["خطة واحدة"]

    def check(self, criterion: str, plan: list[str]) -> bool:
        return "وصولية" not in criterion


class EngineBroken:
    """محرك ينهار — الخط يجب أن يعلن لا أن يهدم."""

    def plan(self, goal: str) -> list[str]:
        raise RuntimeError("انفجار داخلي")

    def check(self, criterion: str, plan: list[str]) -> bool:  # pragma: no cover
        return True


def make_ticket(**over) -> Ticket:
    base = dict(
        id="NT-101",
        title="Add escalation gate",
        goal="Implement escalation on failure for the council engine.",
        acceptance=("escalation field present", "no proactive convocation"),
    )
    base.update(over)
    return Ticket(**base)


# ── التذكرة ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["t101", "nt-101", "NT-", "NT-101-", "NT_101", ""])
def test_ticket_id_pattern_enforced(bad):
    with pytest.raises(ValueError, match="معرف"):
        make_ticket(id=bad)


def test_ticket_requires_acceptance():
    with pytest.raises(ValueError, match="معايير"):
        make_ticket(acceptance=())


def test_ticket_requires_goal_and_title():
    with pytest.raises(ValueError, match="هدف"):
        make_ticket(goal="   ")
    with pytest.raises(ValueError, match="عنوان"):
        make_ticket(title="")


def test_ticket_rejects_unknown_priority():
    with pytest.raises(ValueError, match="أسبقية"):
        make_ticket(priority="urgent")


@pytest.mark.parametrize("p", PRIORITIES)
def test_all_priorities_accepted(p):
    assert make_ticket(priority=p).priority == p


# ── اسم الفرع ────────────────────────────────────────────────────────

def test_branch_follows_pattern():
    assert branch_for(make_ticket()) == "tickets/nt-101-add-escalation-gate"


def test_branch_is_safe_from_hostile_title():
    t = make_ticket(title="../../etc/passwd && rm -rf /")
    branch = branch_for(t)
    assert ".." not in branch
    assert "/" in branch and branch.count("/") == 1  # tickets/ فقط
    assert branch.startswith("tickets/nt-101-")


def test_branch_arabic_title_falls_back_cleanly():
    t = make_ticket(title="بوابة التصعيد")
    assert branch_for(t) == "tickets/nt-101-ticket"


def test_branch_capped_at_limit():
    t = make_ticket(title="a" * 200)
    assert len(branch_for(t)) <= MAX_BRANCH_LENGTH


# ── التنفيذ ──────────────────────────────────────────────────────────

def test_run_with_good_engine_is_done(tmp_path):
    result = TicketRunner(engine=EngineOk(), reports_dir=tmp_path).run(make_ticket())
    assert result.status == "done"
    assert result.branch == "tickets/nt-101-add-escalation-gate"
    assert all(result.checks.values())
    assert result.plan == ("خطوة أولى", "خطوة ثانية")
    assert result.duration_ms >= 0.0


def test_run_without_engine_is_blocked_not_faked(tmp_path):
    result = TicketRunner(reports_dir=tmp_path).run(make_ticket())
    assert result.status == "blocked"
    assert result.checks == {}
    assert result.plan  # تخطيط بديل حتمي موجود
    assert "لا محرك" in result.report_path or Path(result.report_path).exists()


def test_failed_criterion_blocks(tmp_path):
    t = make_ticket(acceptance=("سطر أول", "وصولية كاملة", "سطر ثالث"))
    result = TicketRunner(engine=EnginePartial(), reports_dir=tmp_path).run(t)
    assert result.status == "blocked"
    assert result.checks["سطر أول"] is True
    assert result.checks["وصولية كاملة"] is False
    assert "معايير فاشلة" in Path(result.report_path).read_text(encoding="utf-8")


def test_broken_engine_declares_not_raises(tmp_path):
    result = TicketRunner(engine=EngineBroken(), reports_dir=tmp_path).run(make_ticket())
    assert result.status == "blocked"
    assert "RuntimeError" in Path(result.report_path).read_text(encoding="utf-8")


# ── التقرير ──────────────────────────────────────────────────────────

def test_report_written_and_deterministic(tmp_path):
    t = make_ticket()
    first = TicketRunner(engine=EngineOk(), reports_dir=tmp_path).run(t)
    second = TicketRunner(engine=EngineOk(), reports_dir=tmp_path).run(t)
    a = Path(first.report_path).read_text(encoding="utf-8")
    b = Path(second.report_path).read_text(encoding="utf-8")
    # المدة تتغير — نتحقق من البنية لا الحرفية الكاملة
    for token in ("# تذكرة NT-101", "tickets/nt-101-add-escalation-gate",
                  "## الهدف", "## الخطة", "## معايير القبول", "النشر قرار إنسان"):
        assert token in a and token in b
    assert a.splitlines()[0] == b.splitlines()[0]


def test_report_status_labels(tmp_path):
    done = TicketRunner(engine=EngineOk(), reports_dir=tmp_path).run(make_ticket())
    blocked = TicketRunner(reports_dir=tmp_path).run(make_ticket(id="NT-102"))
    a = Path(done.report_path).read_text(encoding="utf-8")
    b = Path(blocked.report_path).read_text(encoding="utf-8")
    assert "منفَّذة" in a and "محجوبة" in b


# ── التتبع ───────────────────────────────────────────────────────────

def test_trace_event_written(tmp_path, monkeypatch):
    trace_path = tmp_path / "runs" / "trace.jsonl"
    monkeypatch.setenv("NEXUS_TRACE_PATH", str(trace_path))
    TicketRunner(engine=EngineOk(), reports_dir=tmp_path).run(make_ticket())
    lines = trace_path.read_text(encoding="utf-8").strip().splitlines()
    event = json.loads(lines[-1])
    assert event["agent"] == "ticket-runner"
    assert event["tool"] == "run"
    assert event["outcome"] == "done"
    assert event["ticket"] == "NT-101"


def test_trace_disabled(tmp_path, monkeypatch):
    trace_path = tmp_path / "runs" / "trace.jsonl"
    monkeypatch.setenv("NEXUS_TRACE_PATH", str(trace_path))
    TicketRunner(engine=EngineOk(), reports_dir=tmp_path, trace=False).run(make_ticket())
    assert not trace_path.exists()


# ── الحالات المعلنة ──────────────────────────────────────────────────

def test_statuses_contract():
    assert STATUSES == ("done", "blocked", "rejected")


def test_result_rejects_unknown_status():
    with pytest.raises(ValueError, match="حالة غير معروفة"):
        TicketResult(status="published", branch="x", ticket_id="NT-1")
