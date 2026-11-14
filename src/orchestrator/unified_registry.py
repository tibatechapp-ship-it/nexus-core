"""Unified agent registry — المرشحون التسعة والتسعون من الإطارين (ب2.2).

خطة التناغم (``docs/harmony-plan.md`` الموجة 2): التوجيه لا يعرف 20 من 106
بعد اليوم — هذا السجل يجمع:

* **20 وكيلاً core** من ``skills_registry.json`` عبر
  ``src.orchestrator.registry.get_registry`` (مواصفات مهارات كاملة).
* **79 وكيلاً novamind** مُسقطاً من ``src/novamind/registry/data/nova.yaml``
  (yaml metadata فقط — **بلا استيراد وحدات**، بنفس انضباط ``src.fleet.inventory``):
  scope من role/category/capabilities/aliases، وdomain من category،
  وdescription من حقل الوصف.
* الأسماء المشتركة الثمانية: **core الاسمي يفوز** بالاصطدام — نفس قرار
  ``NAME_ALIASES`` في الجرد الموحد (``canonical = core:<name>``) — فالسجل
  يحوي **91 مرشحاً فريداً** لا 99.
* legacy السبعة مستبعَدون معلناً: مكسور/متحلٍّ (طبقة C كلها، والوحيد المكسور
  ``nexus_agent`` منهم) وغير قابل للتنفيذ في مسار المنسق — الاستبعاد قرار
  حوكمة معلن لا غفلة.

التوجيه من هذا السجل يجعل كل قرار يحمل الإطار (`framework`) فتصير مفاتيح
لوحة الأسطول ``{(framework, name)}`` صحيحة أخيراً (ب2.1)، والسلّم
(``ladder``) يرتب المرشحين بالدرجة الحية عبر ``src.fleet.reader``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from src.orchestrator.registry import AgentRegistry, AgentSpec, get_registry

__all__ = ["get_unified_registry", "UNIFIED_TOTAL", "NOVA_YAML"]

ROOT = Path(__file__).resolve().parents[2]
NOVA_YAML = ROOT / "src" / "novamind" / "registry" / "data" / "nova.yaml"

#: عدد المرشحين الفريدين: 20 core + 79 novamind ناقص 8 أسماء مشتركة يفوز
#: بها core (نفس قرار NAME_ALIASES) = 91 — وlegacy السبعة مستبعَدون معلناً.
UNIFIED_TOTAL = 91


def _novamind_specs() -> List[AgentSpec]:
    """اسقط سجلات nova.yaml إلى واصفات توجيه — yaml بلا استيراد وحدات."""
    import yaml  # تبعية معلنة في المشروع (pyproject) — تُستخدم في fleet/inventory.py

    try:
        data = yaml.safe_load(NOVA_YAML.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return []  # معلن: غياب السجل لا يهدم السجل الموحد — core يبقى كاملاً
    roles = data.get("agents") if isinstance(data, dict) else None
    if not isinstance(roles, dict):
        return []
    specs: List[AgentSpec] = []
    for name, row in roles.items():
        if not isinstance(row, dict):
            continue
        category = str(row.get("category", "general"))
        capabilities = [str(c) for c in (row.get("capabilities") or [])
                        if isinstance(c, str)]
        aliases = [str(a) for a in (row.get("aliases") or []) if isinstance(a, str)]
        role = str(row.get("role", "tool"))
        scope = tuple(dict.fromkeys([role, category, *capabilities, *aliases, name]))
        specs.append(AgentSpec(
            name=str(name),
            domain=f"novamind.{category}",
            scope=scope,
            not_scope=(),
            input_schema={},
            output_schema={},
            framework="novamind",
            description=str(row.get("description", "")),
        ))
    return specs


class UnifiedRegistry:
    """غلاف يجمع سجل core المعتمد مع إسقاط novamind — core يفوز بالاصطدام."""

    def __init__(self) -> None:
        self._core = get_registry()
        self._specs: Dict[str, AgentSpec] = {}
        for spec in self._core.all():
            self._specs[spec.name] = spec
        self._novamind_count = 0
        for spec in _novamind_specs():
            if spec.name in self._specs:
                continue  # الأسماء الثمانية المشتركة: core الاسمي يفوز (معلن)
            self._specs[spec.name] = spec
            self._novamind_count += 1

    def get(self, name: str) -> AgentSpec:
        return self._core.get(name)

    def spec(self, name: str) -> Optional[AgentSpec]:
        return self._specs.get(name)

    def all(self) -> List[AgentSpec]:
        return list(self._specs.values())

    def __len__(self) -> int:
        return len(self._specs)

    @property
    def novamind_count(self) -> int:
        """كم وكيلاً novamind دخل السجل فعلاً (79 صحيًا، أقل إن فساد yaml)."""
        return self._novamind_count


_unified: Optional[UnifiedRegistry] = None


def get_unified_registry() -> UnifiedRegistry:
    """السجل الموحد — singleton كسائر سجلات المنصة."""
    global _unified
    if _unified is None:
        _unified = UnifiedRegistry()
    return _unified
