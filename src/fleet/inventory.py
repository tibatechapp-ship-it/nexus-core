"""Fleet Inventory — الجرد الموحد لكل وكلاء المستودع.

مصدر الحقيقة الوحيد لسؤال «كم عندنا وكيلاً وأين هم؟». يكتشف الوكلاء من ثلاث
جهات معلنة:

1. **novamind** — سجل ``src/novamind/registry/data/nova.yaml`` (79 مدخلاً
   معلنة الوحدات والأصناف والأدوار).
2. **core** — الإطار الأساسي ``src.agents.AGENT_CLASSES`` (عشرون وكيلاً
   مضمّنين في الحزمة نفسها).
3. **legacy** — وحدات الجذر القديمة التي تقدّم نقطة دخول وكيلية قائمة بذاتها
   (قائمة صريحة معلنة أدناه — لا تخمين بالأسماء).

الجرد قراءة بحتة: لا استيراد لوحدات الوكلاء هنا (ذلك عمل فحص المطابقة)،
ولا شبكة، ولا كتابة.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

from src.fleet.record import AgentRecord

__all__ = ["build_inventory", "reconcile", "summary", "LEGACY_AGENTS"]

ROOT = Path(__file__).resolve().parents[2]
NOVA_YAML = ROOT / "src" / "novamind" / "registry" / "data" / "nova.yaml"

#: وحدات الجذر القديمة المعترف بها كوكلاء/خدمات وكيلية — قائمة صريحة لا
#: استنتاج بالاسم: كل مدخل يجب أن يوجد فعلاً وإلا رُصد في المطابقة.
LEGACY_AGENTS: tuple[tuple[str, str, str, str], ...] = (
    # (module, symbol, role, description)
    ("hyper_agent", "autonomous_workflow_hyper", "manager", "محرك سير العمل الذاتي 2.0"),
    ("unified_agent", "UnifiedChat", "manager", "الوكيل الموحد v10 (خادم)"),
    ("nexus_agent", "CouncilRequest", "manager", "خادم Nexus-Core الموحد"),
    ("pr_reviewer", "PRReviewer", "tool", "مراجع طلبات الدمج مع حلقة تعلّم"),
    ("review_engine", "load_agents", "manager", "محرك المراجعة — تحميل 42 وكيلاً"),
    ("groq_pool", "GroqKeyPool", "service", "مجمّع مفاتيح Groq"),
    ("safe_runner", "SafeRunner", "service", "حاضنة تنفيذ آمنة"),
)

#: مفردات الفئة لكل إطار — الإطارات لا تتشارك تقاليد، والتحقق يُراعى ذلك.
CATEGORIES: dict[str, frozenset[str]] = {
    "novamind": frozenset(
        {"code", "quality", "security", "infra", "data", "research", "ui", "meta"}
    ),
    "core": frozenset({"core", "planning", "quality", "ops"}),
    "legacy": frozenset({"meta"}),
}
_CRITICALITIES = frozenset({"core", "standard", "optional"})


def _repo_version() -> str:
    """قراءة إصدار المستودع من ``pyproject.toml`` (مصدر الحقيقة الوحيد)."""
    try:
        with open(ROOT / "pyproject.toml", "rb") as f:
            return str(tomllib.load(f)["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"


def _novamind_records() -> list[AgentRecord]:
    """79 سجلاً من ``nova.yaml`` — metadata فقط، بلا استيراد وحدات."""
    with open(NOVA_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    records: list[AgentRecord] = []
    for name, meta in data.get("agents", {}).items():
        records.append(
            AgentRecord(
                name=str(name),
                framework="novamind",
                source=_module_source(str(meta.get("module", ""))),
                module=str(meta.get("module", "")),
                symbol=str(meta.get("class_name", "")),
                role=str(meta.get("role", "tool")),
                category=str(meta.get("category", "meta")),
                criticality=str(meta.get("criticality", "standard")),
                description=str(meta.get("description", "")),
                main_function=str(meta.get("main_function", "")),
            )
        )
    return records


def _module_source(module: str) -> str:
    """تحويل مسار وحدة إلى مسار ملف نسبي معلن.

    ``novamind.*`` يُستورد باسم أعلى من ``src/`` فيُساق إلى ``src/novamind/…``؛
    سائر الوحدات (``src.*``، وحدات الجذر) تُساق كما هي.
    """
    if not module:
        return ""
    if module.startswith("novamind."):
        return "src/" + module.replace(".", "/") + ".py"
    return module.replace(".", "/") + ".py"


def _core_records() -> list[AgentRecord]:
    """عشرون سجلاً من ``AGENT_CLASSES`` — الهوية من الصنف نفسه."""
    from src.agents import AGENT_CLASSES  # استيراد محلي: يمنع دورة الاستيراد

    records: list[AgentRecord] = []
    for cls in AGENT_CLASSES:
        records.append(
            AgentRecord(
                name=str(cls.name),
                framework="core",
                source="src/agents/" + Path(cls.__module__).name + ".py",
                module=cls.__module__,
                symbol=cls.__name__,
                role="tool",
                category=str(getattr(cls, "group", "core")),
                criticality="core",
                description=str(getattr(cls, "description", "")),
            )
        )
    return records


def _legacy_records() -> list[AgentRecord]:
    """سجلات الجذر القديمة — الحضور يُتحقق منه في المطابقة لا هنا."""
    return [
        AgentRecord(
            name=module,
            framework="legacy",
            source=module + ".py",
            module=module,
            symbol=symbol,
            role=role,
            category="meta",
            criticality="optional",
            description=description,
        )
        for module, symbol, role, description in LEGACY_AGENTS
    ]


def build_inventory() -> list[AgentRecord]:
    """أسطول موحّد مفرز: novamind ثم core ثم legacy، وكل فئة أبجدياً."""
    records = _novamind_records() + _core_records() + _legacy_records()
    order = {fw: i for i, fw in enumerate(("novamind", "core", "legacy"))}
    return sorted(records, key=lambda r: (order[r.framework], r.name))


def reconcile(records: list[AgentRecord]) -> dict:
    """مطابقة السجل مع الكود الفعلي — تعارضات معلنة لا صمت.

    يفحص: الازدواج **داخل** الإطار الواحد، تشارك الاسم **بين** الإطارات
    (معلومة توحيد لا خطأ — لكل إطار مفردات أسماء مستقلة)، فئات غير معروفة
    بمفردات الإطار نفسه، حرجيات غير معروفة، ومداخل novamind التي لا يقابلها
    ملف وحدة على القرص.
    """
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    overlap: dict[str, list[str]] = {}
    bad_category: list[str] = []
    bad_criticality: list[str] = []
    missing_file: list[str] = []
    for rec in records:
        key = f"{rec.framework}:{rec.name}"
        if key in seen:
            duplicates.append(f"{key} (also at {seen[key]})")
        seen.setdefault(key, key)
        overlap.setdefault(rec.name, [])
        if rec.framework not in overlap[rec.name]:
            overlap[rec.name].append(rec.framework)
        if rec.category not in CATEGORIES.get(rec.framework, frozenset()):
            bad_category.append(f"{rec.name}: {rec.category!r} ({rec.framework})")
        if rec.criticality not in _CRITICALITIES:
            bad_criticality.append(f"{rec.name}: {rec.criticality!r}")
        if rec.framework == "novamind" and rec.source:
            if not (ROOT / rec.source).is_file():
                missing_file.append(rec.name)
    return {
        "duplicates": duplicates,
        "cross_framework_overlap": sorted(name for name, fws in overlap.items() if len(fws) > 1),
        "bad_category": bad_category,
        "bad_criticality": bad_criticality,
        "missing_module_file": missing_file,
    }


def summary(records: list[AgentRecord]) -> dict:
    """ملخص تنفيذي: العدد الكلي وتوزيعه بالإطار والدور والفئة + الإصدار."""
    by_framework: dict[str, int] = {}
    by_role: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for rec in records:
        by_framework[rec.framework] = by_framework.get(rec.framework, 0) + 1
        by_role[rec.role] = by_role.get(rec.role, 0) + 1
        by_category[rec.category] = by_category.get(rec.category, 0) + 1
    return {
        "total": len(records),
        "version": _repo_version(),
        "by_framework": dict(sorted(by_framework.items())),
        "by_role": dict(sorted(by_role.items())),
        "by_category": dict(sorted(by_category.items())),
    }
