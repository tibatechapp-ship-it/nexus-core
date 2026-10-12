"""
NovaMind Planner v3.0
======================
المُخطط — يختار Pipeline المناسب للمهمة.

يستخدم:
    - registry_v2 (لتصنيف المهام)
    - hive.factory.pipeline.PIPELINES (للمصانع المتاحة)

الاستخدام:
    from novamind.planner import Planner

    planner = Planner()
    decision = planner.decide("أصلح خطأ في coder.py")
    print(decision.pipeline_id)  # "bug_fix"
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from novamind.registry_v2 import REGISTRY, Category

logger = logging.getLogger("novamind.planner")


# ═══════════════════════════════════════════════════════════════
# Decision
# ═══════════════════════════════════════════════════════════════

@dataclass
class PlanDecision:
    """قرار التخطيط."""
    task: str
    pipeline_id: str
    category: Category
    confidence: float = 0.0
    keywords: List[str] = field(default_factory=list)
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "pipeline_id": self.pipeline_id,
            "category": self.category.value,
            "confidence": round(self.confidence, 2),
            "keywords": self.keywords,
            "reasoning": self.reasoning,
        }

    def summary(self) -> str:
        lines = [
            "=" * 60,
            "📋 Plan Decision",
            "=" * 60,
            f"Task:       {self.task[:70]}",
            f"Pipeline:   {self.pipeline_id}",
            f"Category:   {self.category.value}",
            f"Confidence: {self.confidence:.0%}",
            f"Reasoning:  {self.reasoning}",
            "=" * 60,
        ]
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Category Detection
# ═══════════════════════════════════════════════════════════════

CATEGORY_KEYWORDS = {
    Category.CODE: [
        "code", "function", "class", "implement", "write", "refactor",
        "bug", "fix", "test", "review",
        "كود", "دالة", "اكتب", "أصلح", "خطأ", "اختبر", "راجع",
    ],
    Category.SECURITY: [
        "security", "auth", "vulnerability", "xss", "injection",
        "encrypt", "secret",
        "أمان", "تسجيل دخول", "مصادقة", "تشفير",
    ],
    Category.QUALITY: [
        "review", "quality", "lint", "analyze", "document", "format",
        "جودة", "تحليل", "توثيق", "مراجعة",
    ],
    Category.INFRA: [
        "deploy", "docker", "k8s", "kubernetes", "ci", "cd", "build",
        "نشر", "بناء", "بنية",
    ],
    Category.DATA: [
        "data", "sql", "database", "query", "etl",
        "بيانات", "قاعدة بيانات",
    ],
    Category.UI: [
        "ui", "css", "react", "vue", "html", "frontend",
        "واجهة", "تصميم",
    ],
    Category.RESEARCH: [
        "research", "plan", "design", "architecture",
        "بحث", "تخطيط", "معمارية",
    ],
    Category.META: [
        "meta", "agent", "system", "monitor", "heal",
        "نظام", "مراقبة", "شفاء",
    ],
}


def detect_category(task: str) -> tuple[Category, List[str]]:
    """يكتشف تصنيف المهمة والكلمات المفتاحية."""
    task_lower = task.lower()
    scores: Dict[Category, int] = {c: 0 for c in Category}
    matched_keywords: List[str] = []

    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in task_lower:
                scores[cat] += 1
                matched_keywords.append(kw)

    best_cat = max(scores, key=scores.get)
    if scores[best_cat] == 0:
        return Category.CODE, []
    return best_cat, matched_keywords


# ═══════════════════════════════════════════════════════════════
# Planner
# ═══════════════════════════════════════════════════════════════

# ربط Category → Pipeline
CATEGORY_PIPELINE_MAP = {
    Category.INFRA: "deploy",
    Category.QUALITY: "code_review",
    Category.CODE: "system_creation",
    Category.SECURITY: "system_creation",
    Category.DATA: "system_creation",
    Category.UI: "system_creation",
    Category.RESEARCH: "system_creation",
    Category.META: "system_creation",
}

# كلمات مفتاحية خاصة لكل pipeline
PIPELINE_TRIGGERS = {
    "bug_fix": [
        "bug", "fix", "error", "broken", "fail",
        "أصلح", "خطأ", "معطل", "لا يعمل",
    ],
    "code_review": [
        "review", "check", "audit", "inspect",
        "راجع", "افحص", "مراجعة", "تدقيق",
    ],
    "deploy": [
        "deploy", "release", "publish", "ship",
        "نشر", "إطلاق", "رفع",
    ],
    "system_creation": [
        "create", "build", "make", "implement", "write",
        "أنشئ", "ابنِ", "اكتب", "طوّر",
    ],
}


class Planner:
    """
    المُخطط — يختار Pipeline المناسب.

    الاستخدام:
        planner = Planner()
        decision = planner.decide("أصلح خطأ في coder.py")
    """

    def __init__(self):
        self.registry = REGISTRY

    # ═══════════════════════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════════════════════

    def decide(self, task: str) -> PlanDecision:
        """
        يقرر الـ Pipeline المناسب.

        Args:
            task: وصف المهمة

        Returns:
            PlanDecision
        """
        logger.info(f"📋 Planning: {task[:80]}")

        # 1. اكتشف Category
        category, keywords = detect_category(task)

        # 2. ابحث عن trigger خاص
        task_lower = task.lower()
        special_pipeline = None
        matched_trigger = None

        for pipeline_id, triggers in PIPELINE_TRIGGERS.items():
            for trigger in triggers:
                if trigger in task_lower:
                    special_pipeline = pipeline_id
                    matched_trigger = trigger
                    break
            if special_pipeline:
                break

        # 3. القرار النهائي
        if special_pipeline:
            pipeline_id = special_pipeline
            confidence = 0.9
            reasoning = f"Special trigger: '{matched_trigger}' → {pipeline_id}"
        else:
            pipeline_id = CATEGORY_PIPELINE_MAP.get(category, "system_creation")
            confidence = 0.7 if keywords else 0.5
            reasoning = f"Category '{category.value}' → {pipeline_id}"

        decision = PlanDecision(
            task=task,
            pipeline_id=pipeline_id,
            category=category,
            confidence=confidence,
            keywords=keywords[:10],
            reasoning=reasoning,
        )

        logger.info(
            f"✅ Decision: {decision.pipeline_id} "
            f"(confidence: {decision.confidence:.0%})"
        )
        return decision

    # ═══════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════

    def list_available_pipelines(self) -> List[Dict[str, Any]]:
        """يُعيد قائمة الـ pipelines المتاحة."""
        try:
            from hive.factory.pipeline import list_pipelines
            return list_pipelines()
        except ImportError:
            return []


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def _cli_main() -> int:
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python -m nova.planner '<task>'")
        return 1

    task = " ".join(sys.argv[1:])
    planner = Planner()

    if "--json" in sys.argv:
        decision = planner.decide(task)
        print(json.dumps(decision.to_dict(), indent=2, ensure_ascii=False))
    elif "--list" in sys.argv:
        pipelines = planner.list_available_pipelines()
        for p in pipelines:
            print(f"  • {p.get('id', '?'):20s} — {p.get('name', '?')}")
    else:
        decision = planner.decide(task)
        print(decision.summary())

    return 0


__all__ = [
    "Planner",
    "PlanDecision",
    "detect_category",
]


if __name__ == "__main__":
    import sys
    sys.exit(_cli_main())
