#!/usr/bin/env python3
"""
Hive Factory Registry — Agent Metadata & Discovery (Final v3.1)
================================================================
سجل مركزي لتعريف الوكلاء، خصائصهم، وطرق استدعائهم.
يدعم 'signature_map' لمرونة أعلى في توقيعات الدوال.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger("hive.factory.registry")


@dataclass
class AgentSpec:
    """
    مواصفات وكيل واحد.
    
    Attributes:
        name: المعرف الفريد للوكيل.
        category: التصنيف (analysis, coding, security...).
        module: مسار الوحدة النمطية (e.g., nova.agents.coder).
        class_name: اسم الـ class أو الـ instance داخل الوحدة (حسب الحالة).
        method: اسم الدالة الرئيسية للاستدعاء.
        timeout_seconds: الحد الزمني الأقصى للتنفيذ.
        max_cost_usd: سقف التكلفة التقديرية للمهمة الواحدة.
        signature_map: خريطة تحويل:
            - "task"        → يُترجم لقيمة task
            - "ctx"         → يُترجم لقاموس ctx كاملاً
            - "ctx.<key>"   → يُترجم لقيمة ctx["<key>"]
    """
    name: str
    category: str
    module: str
    class_name: str
    method: str
    timeout_seconds: int = 120
    max_cost_usd: float = 0.10
    signature_map: Dict[str, str] = field(default_factory=dict)

    def get_kwargs_mapping(self) -> Dict[str, str]:
        return self.signature_map if self.signature_map else {}


class AgentRegistry:
    """سجل الوكلاء العام (Singleton)."""
    
    _instance: Optional['AgentRegistry'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._specs = {}
            logger.info("🏭 Initialized Global Agent Registry")
        return cls._instance

    def register(self, spec: AgentSpec) -> None:
        if spec.name in self._specs:
            logger.warning(f"⚠️ Overwriting: {spec.name}")
        self._specs[spec.name] = spec
        logger.debug(f"✅ Registered: {spec.name} ({spec.category})")

    def get(self, name: str) -> Optional[AgentSpec]:
        return self._specs.get(name)

    def list_all(self) -> List[str]:
        return list(self._specs.keys())

    def list_by_category(self, category: str) -> List[str]:
        return [n for n, s in self._specs.items() if s.category == category]

    def get_categories(self) -> List[str]:
        return sorted(set(s.category for s in self._specs.values()))

    @property
    def specs(self) -> Dict[str, AgentSpec]:
        return self._specs

    def stats(self) -> Dict[str, Any]:
        cats = {}
        for s in self._specs.values():
            cats[s.category] = cats.get(s.category, 0) + 1
        return {
            "total": len(self._specs),
            "categories": len(cats),
            "by_category": cats,
        }


# ═══════════════════════════════════════════════════════════════
# Global Singleton
# ═══════════════════════════════════════════════════════════════
registry = AgentRegistry()
AGENT_REGISTRY = registry  # Alias


# ═══════════════════════════════════════════════════════════════
# Default Agents Registration
# ═══════════════════════════════════════════════════════════════
def _register_defaults():
    """يسجل الوكلاء الأساسية الأربعة."""
    
    defaults = [
        # 1. Analyzer — يستقبل code (task) + filename (from ctx)
        AgentSpec(
            name="analyzer",
            category="analysis",
            module="nova.agents.multilang_analyzer",
            class_name="multilang_analyzer",       # ← instance (lowercase)
            method="analyze",
            timeout_seconds=30,
            signature_map={
                "task": "code",
                "ctx.filename": "filename",
            },
        ),
        
        # 2. Coder — يستقبل request (task)
        AgentSpec(
            name="coder",
            category="coding",
            module="nova.agents.coder",
            class_name="coder",                    # ← instance (lowercase)
            method="build",
            timeout_seconds=60,
            signature_map={
                "task": "request",
            },
        ),
        
        # 3. Test Generator — يستقبل code (task) + filename (from ctx)
        AgentSpec(
            name="test_generator",
            category="testing",
            module="nova.agents.test_generator",
            class_name="test_generator",           # ← instance (lowercase)
            method="generate",
            timeout_seconds=45,
            signature_map={
                "task": "code",
                "ctx.filename": "filename",
            },
        ),
        
        # 4. Fixer — يستقبل code (task) + error + issues (from ctx)
        AgentSpec(
            name="fixer",
            category="maintenance",
            module="nova.agents.fixer",
            class_name="fixer_agent",              # ← instance (lowercase)
            method="fix",
            timeout_seconds=90,
            signature_map={
                "task": "code",
                "ctx.error": "error",
                "ctx.issues": "issues",
            },
        ),
    ]
    
    for spec in defaults:
        registry.register(spec)


# تنفيذ التسجيل عند استيراد الوحدة لأول مرة
_register_defaults()

