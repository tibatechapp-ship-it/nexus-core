"""اختبارات جرد الأسطول — المصدر الوحيد لحقيقة «كم عندنا وكيلاً وأين؟».

العقد المُختبَر: الجرد كامل (79 novamind + 20 أساسي + 7 قديمة = 106)،
مفرز حتمياً، سجلاته متجمدة بمخطط كامل، والمطابقة تعكس واقع القرص.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from src.fleet.inventory import (
    LEGACY_AGENTS,
    ROOT,
    build_inventory,
    reconcile,
    summary,
)
from src.fleet.record import AgentRecord, FRAMEWORKS

EXPECTED_TOTAL = 106
EXPECTED_BY_FRAMEWORK = {"novamind": 79, "core": 20, "legacy": 7}

#: التقاطع المعلن بين مفردات الإطارين — مرشّح توحيد مستقبلي لا خطأ جرد.
#: ب2.1 (v1.49.1): الأسماء الثمانية المشتركة قيانية في core وكل ما
#: يحملها في novamind معلن alias — فلا تعارضاً صامتاً بعد اليوم.
EXPECTED_OVERLAP = {
    "architect",
    "coder",
    "compliance",
    "devops",
    "documentation",
    "performance",
    "refactor",
    "tester",
}


def test_inventory_total_matches_plan() -> None:
    records = build_inventory()
    assert len(records) == EXPECTED_TOTAL
    by_fw = summary(records)["by_framework"]
    assert by_fw == EXPECTED_BY_FRAMEWORK


def test_inventory_is_deterministic_and_sorted() -> None:
    first, second = build_inventory(), build_inventory()
    assert first == second  # بلا عشوائية ولا ساعة — لقطة قابلة للمقارنة
    order = {fw: i for i, fw in enumerate(("novamind", "core", "legacy"))}
    keys = [(order[r.framework], r.name) for r in first]
    assert keys == sorted(keys)


def test_record_schema_is_complete() -> None:
    for rec in build_inventory():
        assert rec.name and rec.framework in FRAMEWORKS
        assert rec.module and rec.symbol, rec.name
        assert rec.role in {"tool", "manager", "service"}, rec.name
        assert isinstance(rec.to_json(), dict)
        assert rec.to_json()["name"] == rec.name


def test_record_is_frozen() -> None:
    rec = build_inventory()[0]
    with pytest.raises(Exception):  # noqa: B017 — dataclass.FrozenInstanceError
        rec.name = "hacked"  # type: ignore[misc]


def test_novamind_records_carry_registry_metadata() -> None:
    records = [r for r in build_inventory() if r.framework == "novamind"]
    analyzer = next(r for r in records if r.name == "analyzer")
    assert analyzer.module == "novamind.agents.analyzer"
    assert analyzer.symbol == "AnalyzerAgent"
    assert analyzer.category == "quality"
    assert analyzer.criticality == "core"
    assert analyzer.main_function == "analyze"


def test_core_records_come_from_agent_classes() -> None:
    records = [r for r in build_inventory() if r.framework == "core"]
    architect = next(r for r in records if r.name == "architect")
    assert architect.module == "src.agents.architect"
    assert architect.symbol == "ArchitectAgent"
    assert architect.criticality == "core"


def test_legacy_records_are_the_explicit_seven() -> None:
    records = [r for r in build_inventory() if r.framework == "legacy"]
    assert {r.name for r in records} == {m.rsplit(".", 1)[-1] for m, *_ in LEGACY_AGENTS}
    assert len(LEGACY_AGENTS) == 7


def test_summary_shape_and_version() -> None:
    records = build_inventory()
    info = summary(records)
    with open(ROOT / "pyproject.toml", "rb") as f:
        pyproject_version = tomllib.load(f)["project"]["version"]
    assert info["total"] == EXPECTED_TOTAL
    assert info["version"] == pyproject_version  # الجرد يعلن إصداره بدقة
    assert set(info["by_category"]) and set(info["by_role"])


def test_reconcile_clean_on_current_fleet() -> None:
    report = reconcile(build_inventory())
    assert report["duplicates"] == []
    assert report["bad_category"] == []
    assert report["bad_criticality"] == []
    assert report["missing_module_file"] == []
    # ب2.1: التوحيد المعلن أفرغ التعارض — الأسماء الثمانية في aliases
    assert report["cross_framework_overlap"] == []
    assert set(report["aliases"]) == EXPECTED_OVERLAP
    for name, info in report["aliases"].items():
        assert info["canonical"] == f"core:{name}"
        assert info["aliases"] == ["novamind"]


def test_alias_records_are_marked_non_canonical() -> None:
    """ب2.1: الجرد يعرض canonical: false لمراكب الأسماء الموحدة."""
    from src.fleet.inventory import NAME_ALIASES

    records = build_inventory()
    for rec in records:
        if rec.framework == "novamind" and rec.name in NAME_ALIASES:
            assert rec.canonical is False, rec.name
        else:
            assert rec.canonical is True, rec.name
    aliased = [r for r in records if r.framework == "novamind" and not r.canonical]
    assert len(aliased) == 8


def test_reconcile_catches_duplicates_and_bad_metadata() -> None:
    real_source = "src/agents/base.py"  # موجود فعلاً فلا يلوث فحص الملفات
    records = [
        AgentRecord(
            name="x",
            framework="novamind",
            source=real_source,
            module="m",
            symbol="S",
            category="not-a-category",
        ),
        AgentRecord(name="x", framework="novamind", source=real_source, module="m", symbol="S"),
        AgentRecord(
            name="y",
            framework="core",
            source=real_source,
            module="m",
            symbol="S",
            category="core",
            criticality="urgent",
        ),
        AgentRecord(
            name="ghost", framework="novamind", source="src/ghost.py", module="m", symbol="S"
        ),
    ]
    report = reconcile(records)
    assert len(report["duplicates"]) == 1
    assert "novamind:x" in report["duplicates"][0]
    assert report["bad_category"] == ["x: 'not-a-category' (novamind)"]
    assert report["bad_criticality"] == ["y: 'urgent'"]
    assert report["missing_module_file"] == ["ghost"]
    assert report["cross_framework_overlap"] == []  # نفس الاسم داخل إطار واحد


def test_module_source_mapping(tmp_path: Path) -> None:
    from src.fleet.inventory import _module_source

    assert _module_source("novamind.agents.analyzer") == "src/novamind/agents/analyzer.py"
    assert _module_source("src.agents.architect") == "src/agents/architect.py"
    assert _module_source("src.legacy_root.hyper_agent") == "src/legacy_root/hyper_agent.py"
    assert _module_source("") == ""


def test_repo_version_fallbacks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """كل إخفاق قراءة الإصدار يهبط بأمان إلى unknown لا انهيار."""
    import src.fleet.inventory as inv

    broken = tmp_path / "broken.toml"
    broken.write_text("[project\nnot toml at all", encoding="utf-8")
    missing_key = tmp_path / "missing_key.toml"
    missing_key.write_text('[project]\nname = "x"\n', encoding="utf-8")

    monkeypatch.setattr(inv, "ROOT", tmp_path)
    (tmp_path / "pyproject.toml").write_bytes(broken.read_bytes())
    assert inv._repo_version() == "unknown"
    (tmp_path / "pyproject.toml").write_text(missing_key.read_text(encoding="utf-8"))
    assert inv._repo_version() == "unknown"
    monkeypatch.undo()
    assert inv._repo_version() != "unknown"  # الحقيقي سليم بعد الاستعادة
