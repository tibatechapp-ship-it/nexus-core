"""اختبارات مطابقة الأسطول — **وكيل واحد، قضية اختبار واحدة** لكل الأسطول.

هذا هو الاختبار القوي المطلوب لكل الوكلاء: كل سجل من الـ106 يُفحص فردياً
(استيراد حقيقي + نقطة دخول حاضرة)، والكسر معلن بقوائم أسباب لا بأعداد:

* ``KNOWN_BROKEN`` — مكسور في كل البيئات (إصلاحه يُفشل الاختبار فيُجبر
  المُصلِح على تحديث القائمة). **فارغة منذ 1.48.1**: إصلاح ``pr_reviewer``
  (استيرادات مرنة معلنة) أفرغها — وعقد «لا رجوع للوراء» يُفشل أي عودة للكسر.
* ``OPTIONAL_ENV_BROKEN`` — يتطلب إضافة اختيارية قد تكون غائبة (مثل
  ``sse-starlette`` على CI) فيُقبل سليماً أو مكسوراً بسبب استيراد معلن.
* أي وكيل آخر مكسور = تراجع جديد ⇒ فشل اختبار. لا صمت.
"""

from __future__ import annotations

import pytest

from src.fleet.conformance import SilentBackend, check_agent, run_conformance
from src.fleet.inventory import build_inventory
from src.fleet.record import AgentRecord

#: مكسور معلن في كل البيئات مع سببه — لا يُسمح بكسر جديد، وإصلاح يوجب حذفاً.
#: فارغة منذ 1.48.1: إصلاح pr_reviewer (استيرادات مرنة معلنة لا تعتمد على
#: أي إضافة اختيارية) جعله سليماً في كل البيئات — عقد «لا رجوع للوراء».
KNOWN_BROKEN: dict[str, str] = {}

#: مكسور حيث تُغيب إضافته الاختيارية فقط (CI بلا sse-starlette) — صادق بيئياً.
OPTIONAL_ENV_BROKEN: dict[str, str] = {
    "nexus_agent": "يتطلب sse-starlette (إضافة اختيارية غائبة على CI)",
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
    elif rec.name in OPTIONAL_ENV_BROKEN:
        if report["status"] == "broken":
            assert any(r.startswith("import:") for r in report["reasons"]), (
                "كسر الوكيل الحساس للبيئة يجب أن يكون سببه الاستيراد"
            )
    else:
        assert report["status"] == "healthy", report["reasons"]


def test_conformance_aggregates_match_per_agent_truth() -> None:
    conf = run_conformance(ALL_RECORDS)
    assert conf["checked"] == len(ALL_RECORDS)
    counts = conf["counts"]
    broken_names = {r["name"] for r in conf["reports"]
                    if r["status"] == "broken"}
    # لا كسر جديد خارج قوائم الصدق — وأصل المعلن مكسور دائماً
    allowed = set(KNOWN_BROKEN) | set(OPTIONAL_ENV_BROKEN)
    assert broken_names <= allowed, (
        f"كسور غير معلنة: {broken_names - allowed} — أعلنها في قوائم الصدق"
    )
    assert counts["healthy"] + counts["degraded"] + counts["broken"] == conf["checked"]
    healthy = [r for r in conf["reports"] if r["status"] == "healthy"]
    assert all(r["import_ms"] >= 0 for r in healthy)
    # عقد «لا رجوع للوراء»: pr_reviewer أُصلح في 1.48.1 باستيرادات مرنة معلنة
    # لا تعتمد على أي إضافة اختيارية — سليم في كل البيئات، وكسره تراجع يُفشل.
    assert all(r["status"] == "healthy" for r in conf["reports"]
               if r["name"] == "pr_reviewer")


def test_pr_reviewer_degrades_gracefully_offline() -> None:
    """الوكيل المُصلَح: استيراد آمن + تدهور بنعم معلن بلا عميل GitHub.

    الإصلاح (1.48.1): التبعيات القديمة كلها أعلام ميزات — غيابها يُرجع
    ``ok: False`` بسبب واضح، لا استثناء استيراد يُسقط الأسطول كله.
    """
    import pr_reviewer as mod

    assert isinstance(mod.GITHUB_INTEGRATION_AVAILABLE, bool)
    assert isinstance(mod.ANALYZERS_AVAILABLE, bool)
    assert isinstance(mod.TEST_GENERATOR_AVAILABLE, bool)

    reviewer = mod.PRReviewer(gh=None)
    result = reviewer.review_pr("any/repo", 1)
    assert result["ok"] is False
    assert "unavailable" in result["error"]
    # المفرد على مستوى الوحدة يُبنى آمناً بلا شبكة ولا استثناء وقت الاستيراد
    assert type(mod.pr_reviewer).__name__ == "PRReviewer"


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
