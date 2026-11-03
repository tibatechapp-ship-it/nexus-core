"""اختبارات مطابقة الأسطول — **وكيل واحد، قضية اختبار واحدة** لكل الأسطول.

هذا هو الاختبار القوي المطلوب لكل الوكلاء: كل سجل من الـ106 يُفحص فردياً
(استيراد حقيقي + نقطة دخول حاضرة)، والمكسور الوحيد (``pr_reviewer``) معلن
في قائمة أسباب معروفة — إصلاحه يُفشل الاختبار فيُجبر المُصلِح على تحديث
القائمة، فيمتنع الصمت عن إخفاء أي تراجع.
"""

from __future__ import annotations

import pytest

from src.fleet.conformance import SilentBackend, check_agent, run_conformance
from src.fleet.inventory import build_inventory
from src.fleet.record import AgentRecord

#: وكلاء معروف كسرهم مع سببه — لا يُسمح بكسر جديد، وإصلاح يوجب حذف السطر.
KNOWN_BROKEN: dict[str, str] = {
    "pr_reviewer": "يستورد وحدة integration غير الموجودة في المستودع",
}

ALL_RECORDS = build_inventory()


def _report_map(deep: bool) -> dict:
    conf = run_conformance(ALL_RECORDS, deep=deep)
    return {r["name"]: r for r in conf["reports"]}


@pytest.mark.parametrize("rec", ALL_RECORDS,
                         ids=lambda r: f"{r.framework}:{r.name}")
def test_every_agent_imports_and_exposes_entrypoint(rec: AgentRecord) -> None:
    """الوكيل الواحد: استيراد حقيقي، رمز دخول حاضر، حالة معلنة عادلة."""
    report = check_agent(rec)
    assert report["name"] == rec.name
    if rec.name in KNOWN_BROKEN:
        assert report["status"] == "broken", (
            f"أصلحت {rec.name}؟ احذفه من KNOWN_BROKEN مع سببه"
        )
        assert report["reasons"], "المكسور المعلن يجب أن يعلن سببه"
    else:
        assert report["status"] == "healthy", report["reasons"]


def test_conformance_aggregates_match_per_agent_truth() -> None:
    conf = run_conformance(ALL_RECORDS)
    assert conf["checked"] == len(ALL_RECORDS)
    counts = conf["counts"]
    assert counts["broken"] == len(KNOWN_BROKEN)
    assert counts["healthy"] + counts["degraded"] + counts["broken"] == conf["checked"]
    healthy = [r for r in conf["reports"] if r["status"] == "healthy"]
    assert all(r["import_ms"] >= 0 for r in healthy)


def test_deep_mode_instantiates_core_agents() -> None:
    """الوضع العميق: كل الوكلاء الأساسيين العشرين يُبنون ويُشغَّلون ping."""
    conf = run_conformance(
        [r for r in ALL_RECORDS if r.framework == "core"], deep=True)
    assert conf["counts"]["healthy"] == 20


def test_silent_backend_is_offline_deterministic() -> None:
    assert SilentBackend().generate([("user", "hi")]) == "ok"
    assert SilentBackend().generate([], model="x") == "ok"


def test_missing_module_is_broken_with_reason() -> None:
    ghost = AgentRecord(name="ghost", framework="legacy", source="ghost.py",
                        module="no.such.module_xyz", symbol="Ghost",
                        description="x")
    report = check_agent(ghost)
    assert report["status"] == "broken"
    assert any(r.startswith("import:") for r in report["reasons"])
    assert report["import_ms"] >= 0


def test_missing_symbol_is_broken_not_crash() -> None:
    half = AgentRecord(name="half", framework="legacy", source="record.py",
                       module="src.fleet.record", symbol="NoSuchSymbol",
                       description="x")
    report = check_agent(half)
    assert report["status"] == "broken"
    assert any(r.startswith("entrypoint:") for r in report["reasons"])


def test_empty_metadata_is_broken_without_import() -> None:
    empty = AgentRecord(name="empty", framework="legacy", source="x.py",
                        module="", symbol="")
    report = check_agent(empty)
    assert report["status"] == "broken"
    assert report["reasons"][0].startswith("metadata:")
    assert report["import_ms"] == 0.0  # لم يُحاول استيراد شيء


def test_missing_description_is_degraded() -> None:
    rec = AgentRecord(name="quiet", framework="legacy", source="record.py",
                      module="src.fleet.record", symbol="AgentRecord",
                      description="")
    report = check_agent(rec)
    assert report["status"] == "degraded"
    assert "metadata: empty description" in report["reasons"]


def test_core_agent_run_failure_is_reported() -> None:
    """عميل أساسي run يفشل ⇒ منقوص (degraded) لا سليم — عبر تجنيس الصنف."""
    rec = next(r for r in ALL_RECORDS
               if r.name == "coder" and r.framework == "core")

    class EvilAgentClass:
        def __init__(self, backend: object) -> None:
            self.backend = backend

        name = "evil"

        def run(self, task: str) -> object:
            class R:
                ok = False
            return R()

    import sys
    module = sys.modules[rec.module]
    original = getattr(module, rec.symbol)
    setattr(module, rec.symbol, EvilAgentClass)
    try:
        report = check_agent(rec, instantiate_core=True)
    finally:
        setattr(module, rec.symbol, original)
    assert report["status"] == "degraded"
    assert any("run:" in r for r in report["reasons"])


def test_ensure_src_on_path_appends_when_missing(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """ضمّد src/ عند غيابه — وارفض الإضافة المكررة."""
    import sys

    from src.fleet.conformance import ROOT, ensure_src_on_path

    src = str(ROOT / "src")
    monkeypatch.setattr(sys, "path",
                        [p for p in sys.path if p != src])
    ensure_src_on_path()
    assert sys.path.count(src) == 1
    ensure_src_on_path()
    assert sys.path.count(src) == 1  # لا ازدواج


def test_core_agent_init_crash_is_contained() -> None:
    """بناء الوكيل ينفجر ⇒ منقوص بسبب instantiate/run لا انهيار الفحص."""
    rec = next(r for r in ALL_RECORDS
               if r.name == "coder" and r.framework == "core")

    class ExplodingClass:
        def __init__(self, backend: object) -> None:
            raise RuntimeError("wiring exploded")

    import sys
    module = sys.modules[rec.module]
    original = getattr(module, rec.symbol)
    setattr(module, rec.symbol, ExplodingClass)
    try:
        report = check_agent(rec, instantiate_core=True)
    finally:
        setattr(module, rec.symbol, original)
    assert report["status"] == "degraded"
    assert any("instantiate/run:" in r for r in report["reasons"])
