"""اختبارات src/durable — العقد الدوّم الكامل (docs/V2_ROADMAP.md م2).

القلب: اختبار حقن الفشل التساعي — نفس معيار القياس الذي فاز به LangGraph
على CrewAI في مقارنة الإنتاج المستقلة: عطل مقصود في الخطوة 5 من 9، ثم
استئناف من آخر نقطة صحيحة **بصفر إعادة عمل**، مع بوابة بشرية إلزامية
وسجل تدقيق غير قابل للتلاعب.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.durable import (
    AuditIntegrityError,
    AuditLog,
    DurableFlow,
    FlowRejected,
    InterruptPending,
    SnapshotError,
    canonical_json,
    sign_snapshot,
    verify_snapshot,
)


class DurableCrash(Exception):
    """عطل صناعي لاختبار حقن الفشل."""


# ── snapshots ────────────────────────────────────────────────────────────────────


def test_canonical_json_is_sorted_and_unicode_safe() -> None:
    assert canonical_json({"b": 1, "a": "ع"}) == '{"a":"ع","b":1}'.encode("utf-8")


def test_sign_and_verify_roundtrip_sha256() -> None:
    snap = sign_snapshot({"x": 1}, stage="risk")
    assert snap["integrity"]["algorithm"] == "sha256"
    assert verify_snapshot(snap) is True


def test_tampered_payload_fails_verification() -> None:
    snap = sign_snapshot({"x": 1}, stage="risk")
    snap["snapshot"]["payload"]["x"] = 999
    assert verify_snapshot(snap) is False


def test_hmac_mode_with_env_key_and_key_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_DURABLE_KEY", "k1")
    snap = sign_snapshot({"x": 1}, stage="stage")
    assert snap["integrity"]["algorithm"] == "hmac-sha256"
    assert verify_snapshot(snap) is True
    monkeypatch.setenv("NEXUS_DURABLE_KEY", "k2")
    assert verify_snapshot(snap) is False


def test_unknown_algorithm_raises() -> None:
    snap = sign_snapshot({}, stage="s")
    snap["integrity"]["algorithm"] = "md5"
    with pytest.raises(SnapshotError, match="خوارزمية"):
        verify_snapshot(snap)


def test_broken_structure_raises() -> None:
    with pytest.raises(SnapshotError, match="بنية"):
        verify_snapshot({"nope": True})
    with pytest.raises(SnapshotError, match="stage"):
        sign_snapshot({}, stage="")


def test_parent_sha_links_snapshots() -> None:
    first = sign_snapshot({"s": 1}, stage="a")
    second = sign_snapshot({"s": 2}, stage="b", parent_sha=first["integrity"]["digest"])
    assert second["snapshot"]["parent_sha"] == first["integrity"]["digest"]


def test_load_snapshot_rejects_missing_and_tampered(tmp_path: Path) -> None:
    with pytest.raises(SnapshotError, match="لا يمكن قراءة"):
        snap = sign_snapshot({}, stage="s")
        (tmp_path / "g.json").write_text(json.dumps(snap), encoding="utf-8")
        # ensure the raise path uses a truly missing file
        from src.durable.snapshots import load_snapshot

        load_snapshot(tmp_path / "absent.json")
    snap = sign_snapshot({"v": 1}, stage="s")
    path = tmp_path / "s.json"
    path.write_text(json.dumps(snap), encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["snapshot"]["payload"]["v"] = 2
    path.write_text(json.dumps(data), encoding="utf-8")
    from src.durable.snapshots import load_snapshot

    with pytest.raises(SnapshotError, match="بصمة"):
        load_snapshot(path)


# ── audit log ────────────────────────────────────────────────────────────────────


def test_audit_append_read_roundtrip(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl", actor="tester")
    log.append("checkpoint", detail={"stage": "risk"})
    log.append("interrupt", detail={"reason": "high risk"})
    records = log.read()
    assert len(records) == 2
    assert records[0]["event"] == "checkpoint"
    assert records[1]["prev"] == records[0]["digest"]
    assert len(log) == 2


def test_audit_events_filter(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "a.jsonl")
    log.append("x")
    log.append("y")
    assert [r["event"] for r in log.events("x")] == ["x"]


def test_audit_empty_log_reads_empty(tmp_path: Path) -> None:
    assert AuditLog(tmp_path / "none.jsonl").read() == []


def test_audit_rejects_empty_event(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="event"):
        AuditLog(tmp_path / "a.jsonl").append("")


def test_audit_detects_tampered_line(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    log = AuditLog(path)
    log.append("a")
    log.append("b")
    lines = path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0])
    rec["event"] = "forged"
    lines[0] = json.dumps(rec, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(AuditIntegrityError, match="البصمة"):
        AuditLog(path).read()


def test_audit_detects_deleted_line(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    log = AuditLog(path)
    log.append("a")
    log.append("b")
    log.append("c")
    lines = path.read_text(encoding="utf-8").splitlines()
    del lines[1]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(AuditIntegrityError, match="سلسلة الربط"):
        AuditLog(path).read()


def test_audit_detects_corrupt_json(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    AuditLog(path).append("a")
    path.write_text(path.read_text(encoding="utf-8") + "{not-json\n", encoding="utf-8")
    with pytest.raises(AuditIntegrityError, match="JSON"):
        AuditLog(path).read()


# ── durable flow ─────────────────────────────────────────────────────────────────


def test_flow_checkpoint_and_resume_roundtrip(tmp_path: Path) -> None:
    flow = DurableFlow("f1", store_dir=tmp_path)
    flow.checkpoint("risk", {"level": "low"})
    flow.checkpoint("route", {"agent": "analyst"})
    last = flow.latest()
    assert last is not None
    assert last["stage"] == "route" and last["payload"] == {"agent": "analyst"}
    fresh = DurableFlow("f1", store_dir=tmp_path)
    resumed = fresh.resume()
    assert resumed is not None and resumed["stage"] == "route"


def test_flow_resume_detects_broken_chain(tmp_path: Path) -> None:
    flow = DurableFlow("f2", store_dir=tmp_path)
    flow.checkpoint("a", {"n": 1})
    # لقطة ثانية ببصمة سليمة لكن بأب مفبرك — فحص الربط يلتقطها
    forged = sign_snapshot({"n": 2}, stage="b", parent_sha="deadbeef")
    (flow.store / "0002-b.json").write_text(
        json.dumps(forged, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SnapshotError, match="سلسلة مكسورة"):
        DurableFlow("f2", store_dir=tmp_path).resume()


def test_flow_resume_detects_tampered_payload(tmp_path: Path) -> None:
    """تعديل حمولة نقطة سابقة = بصمة لا تطابق قبل أي استئناف."""
    flow = DurableFlow("f2b", store_dir=tmp_path)
    flow.checkpoint("a", {"n": 1})
    flow.checkpoint("b", {"n": 2})
    target = sorted(flow.store.glob("0001-*.json"))[0]
    data = json.loads(target.read_text(encoding="utf-8"))
    data["snapshot"]["payload"]["n"] = 111
    target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SnapshotError, match="بصمة"):
        DurableFlow("f2b", store_dir=tmp_path).resume()


def test_flow_missing_checkpoint_raises(tmp_path: Path) -> None:
    flow = DurableFlow("f3", store_dir=tmp_path)
    (flow.store / "audit.jsonl").touch()
    with pytest.raises(SnapshotError, match="مفقودة"):
        flow._path_of(7)  # noqa: SLF001 — اختبار داخلي مقصود


def test_flow_invalid_id_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="flow_id"):
        DurableFlow("../evil", store_dir=tmp_path)


def test_flow_interrupt_blocks_then_approve_releases(tmp_path: Path) -> None:
    flow = DurableFlow("f4", store_dir=tmp_path)
    flow.checkpoint("step1", {"n": 1})
    info = flow.interrupt("سطر عالي الخطورة يحتاج عينًا بشرية")
    assert info["flow_id"] == "f4"
    with pytest.raises(InterruptPending):
        flow.checkpoint("step2", {"n": 2})
    flow.resume_after_approval("approve", auditor="رئيس المجلس")
    flow.checkpoint("step2", {"n": 2})
    assert flow.latest() is not None and flow.latest()["stage"] == "step2"  # type: ignore[union-attr]


def test_flow_reject_closes_fail_closed(tmp_path: Path) -> None:
    flow = DurableFlow("f5", store_dir=tmp_path)
    flow.checkpoint("step1", {"n": 1})
    flow.interrupt("قرار مصيري")
    with pytest.raises(FlowRejected):
        flow.resume_after_approval("reject", auditor="مراجع")
    with pytest.raises(InterruptPending):
        flow.checkpoint("step2", {"n": 2})
    events = [r["event"] for r in flow.audit.read()]
    assert "flow_closed" in events


def test_flow_gate_validations(tmp_path: Path) -> None:
    flow = DurableFlow("f6", store_dir=tmp_path)
    with pytest.raises(ValueError, match="سبب"):
        flow.interrupt("")
    with pytest.raises(ValueError, match="decision"):
        flow.interrupt("سبب")
        flow.resume_after_approval("maybe", auditor="x")
    with pytest.raises(ValueError, match="مدقّق"):
        flow.interrupt("سبب2")
        flow.resume_after_approval("approve", auditor="")


def test_flow_audit_records_every_gate_event(tmp_path: Path) -> None:
    flow = DurableFlow("f7", store_dir=tmp_path)
    flow.checkpoint("s1", {})
    flow.interrupt("مراجعة")
    flow.resume_after_approval("approve", auditor="q")
    kinds = [r["event"] for r in flow.audit.read()]
    for expected in ("flow_created", "checkpoint", "interrupt", "human_decision", "resume"):
        assert expected in kinds


# ── اختبار حقن الفشل التساعي — جوهر م2 ───────────────────────────────────────────


def _run_pipeline(
    flow: DurableFlow,
    executed: list[int],
    *,
    crash_before: int | None,
    start_from: int = 1,
) -> None:
    """مشغّل خطوات صادق: يبدأ من موضع الاستئناف المعلن لا من الصفر."""
    for step in range(start_from, 10):
        if crash_before is not None and step == crash_before:
            raise DurableCrash(f"عطل مقصود قبل الخطوة {step}")
        flow.checkpoint(f"step{step}", {"step": step, "result": step * 10})
        executed.append(step)


def test_nine_step_failure_injection_zero_rework(tmp_path: Path) -> None:
    """عطل في الخطوة 5/9 → استئناف من نقطة الخطوة 4 بصفر إعادة عمل."""
    audit = AuditLog(tmp_path / "pipeline-audit.jsonl", actor="pipeline")
    executed_run1: list[int] = []
    flow1 = DurableFlow("pipeline-9", store_dir=tmp_path, audit=audit)
    with pytest.raises(DurableCrash):
        _run_pipeline(flow1, executed_run1, crash_before=5)
    assert executed_run1 == [1, 2, 3, 4]  # الخطوات 1-4 محفوظة، 5 لم تنفذ

    # "عملية جديدة بالكامل": سير مركّب من نفس المتجر — يتحقق من السلسلة ثم يستأنف
    flow2 = DurableFlow("pipeline-9", store_dir=tmp_path, audit=audit)
    resumed = flow2.resume()
    assert resumed is not None
    assert resumed["stage"] == "step4" and resumed["payload"]["step"] == 4

    # بوابة بشرية إلزامية قبل متابعة الخطوة الخطرة
    flow2.interrupt("فشل خطوة 5 — تدقيق بشري قبل إعادة المحاولة")
    with pytest.raises(InterruptPending):
        _run_pipeline(flow2, [], crash_before=None, start_from=5)
    flow2.resume_after_approval("approve", auditor="المشرف")

    executed_run2: list[int] = []
    _run_pipeline(flow2, executed_run2, crash_before=None, start_from=5)
    assert executed_run2 == [5, 6, 7, 8, 9]  # صفر إعادة عمل: 1-4 لم تُلمس
    assert not set(executed_run1) & set(executed_run2)

    # سلسلة النقاط التسع كاملة سليمة بعد كل هذا
    final = DurableFlow("pipeline-9", store_dir=tmp_path, audit=audit).resume()
    assert final is not None and final["stage"] == "step9"
    kinds = [r["event"] for r in audit.read()]
    assert kinds.count("checkpoint") == 9
    assert "interrupt" in kinds and "human_decision" in kinds and "resume" in kinds


def test_nine_step_rejection_stops_pipeline(tmp_path: Path) -> None:
    """الرفض البشري يغلق السير: لا استئناف ولا تجاوز (fail-closed)."""
    audit = AuditLog(tmp_path / "audit2.jsonl", actor="pipeline")
    flow = DurableFlow("pipeline-reject", store_dir=tmp_path, audit=audit)
    executed: list[int] = []
    with pytest.raises(DurableCrash):
        _run_pipeline(flow, executed, crash_before=9)
    assert executed == [1, 2, 3, 4, 5, 6, 7, 8]
    flow.interrupt("الخطوة الأخيرة مصيرية")
    with pytest.raises(FlowRejected):
        flow.resume_after_approval("reject", auditor="لجنة الأمن")
    assert [r for r in audit.events("human_decision")][0]["decision"] == "reject"
    with pytest.raises(InterruptPending):
        flow.checkpoint("step9", {"step": 9})


def test_sign_snapshot_accepts_explicit_key() -> None:
    snap = sign_snapshot({"a": 1}, stage="s", key=b"explicit")
    assert snap["integrity"]["algorithm"] == "hmac-sha256"
    assert verify_snapshot(snap, key=b"explicit") is True
    assert verify_snapshot(snap, key=b"other") is False


def test_verify_snapshot_key_mode_mismatch_is_false_not_error() -> None:
    snap = sign_snapshot({}, stage="s")  # sha256 mode
    assert verify_snapshot(snap, key=b"unexpected") is False


def test_audit_treats_preexisting_garbage_as_corruption(tmp_path: Path) -> None:
    """سطر غير JSON في السجل = فساد معلن — الفشل صاخب لا صامت."""
    path = tmp_path / "a.jsonl"
    path.write_text("garbage-line\n", encoding="utf-8")
    with pytest.raises(AuditIntegrityError, match="JSON"):
        AuditLog(path).read()


def test_flow_audit_defaults_to_internal_log(tmp_path: Path) -> None:
    flow = DurableFlow("f8", store_dir=tmp_path)
    assert flow.audit.path.name == "audit.jsonl"
    assert isinstance(flow.audit.read()[0], dict)


def test_checkpoint_with_none_parent_is_first_link(tmp_path: Path) -> None:
    flow = DurableFlow("f9", store_dir=tmp_path)
    flow.checkpoint("only", {"x": None})
    snap = json.loads(sorted(flow.store.glob("0001-*.json"))[0].read_text(encoding="utf-8"))
    parent: Any = snap["snapshot"]["parent_sha"]
    assert parent is None


# ── إغلاق فجوات التغطية — سلوكيات حدية صريحة ─────────────────────────────────────


def test_audit_hmac_mode_with_env_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """مفتاح البيئة يجعل بصمات السجل صادقة (HMAC) لا تكاملية فقط."""
    monkeypatch.setenv("NEXUS_DURABLE_KEY", "secret-key")
    log = AuditLog(tmp_path / "a.jsonl")
    log.append("signed-event")
    assert len(log.read()) == 1
    lines = (tmp_path / "a.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["digest"] != ""
    # مفتاح آخر = بصمة لا تطابق
    monkeypatch.setenv("NEXUS_DURABLE_KEY", "wrong-key")
    with pytest.raises(AuditIntegrityError, match="البصمة"):
        log.read()


def test_audit_skips_blank_lines_and_counts_only_real(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    log = AuditLog(path)
    log.append("one")
    log.append("two")
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n\n")
    assert len(log) == 2  # الأسطر الفارغة لا تُعد ولا تكسر السلسلة
    assert [r["event"] for r in log.read()] == ["one", "two"]


def test_audit_append_to_existing_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    path.touch()  # ملف موجود فارغ: _last_digest يمر بفرع "لا أسطر"
    log = AuditLog(path)
    log.append("first-after-empty")
    assert [r["event"] for r in log.read()] == ["first-after-empty"]


def test_audit_last_digest_garbage_tail_is_tolerated_for_append(
    tmp_path: Path,
) -> None:
    """الإلحاق فوق سطر غير JSON ينجح (prev فارغة) — والقراءة تكشف الفساد."""
    path = tmp_path / "a.jsonl"
    path.write_text("garbage-line\n", encoding="utf-8")
    log = AuditLog(path)
    log.append("after-garbage")  # لا ينفجر عند الإلحاق
    with pytest.raises(AuditIntegrityError):
        log.read()  # لكن القراءة تصخّب الفساد دومًا


def test_flow_latest_on_fresh_flow_is_none(tmp_path: Path) -> None:
    flow = DurableFlow("fresh", store_dir=tmp_path)
    assert flow.latest() is None
    assert flow.resume() is None


def test_flow_digest_of_zero_is_none(tmp_path: Path) -> None:
    flow = DurableFlow("d0", store_dir=tmp_path)
    assert flow._digest_of(0) is None  # noqa: SLF001 — عقد الربط الأولي
