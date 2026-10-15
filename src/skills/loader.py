"""Skills Loader — نظام المهارات.

المهارة = ملف SKILL.md في ~/.config/nexus/skills/<name>/
تحتوي على: وصف، تعليمات، أمثلة، قواعد.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

__all__ = ["Skill", "SkillLoader"]

SKILLS_DIR = Path.home() / ".config" / "nexus" / "skills"


@dataclass
class Skill:
    """مهارة واحدة."""
    name: str
    description: str
    content: str
    path: Path


class SkillLoader:
    """يحمّل المهارات من المجلد."""

    def __init__(self, base_dir: Path = SKILLS_DIR) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._seed_defaults()

    def _seed_defaults(self) -> None:
        """ينشئ المهارات الافتراضية إن لم توجد."""
        defaults = {
            "code-review": """# Code Review Skill

## الغرض
مراجعة الكود بمعايير احترافية.

## الخطوات
1. اقرأ الكود بالكامل
2. ابحث عن: أخطاء منطقية، مشاكل أمنية، أداء، قابلية القراءة
3. اقترح تحسينات محددة
4. اذكر الملف والسطر لكل ملاحظة

## القواعد
- لا تقل "جيد" بدون سبب
- اذكر مثالاً لكل نقطة ضعف
- رتب حسب الخطورة: حرج > مهم > بسيط
""",
            "security-audit": """# Security Audit Skill

## الغرض
فحص أمني شامل للكود.

## الفحوصات الإلزامية
1. XSS (innerHTML, eval, document.write)
2. SQL Injection (string concatenation)
3. Path Traversal (../ في المسارات)
4. Command Injection (subprocess, os.system)
5. Secrets Leak (.env, tokens)
6. Insecure Transport (http://)

## التصنيف
- 🔴 حرج (يسمح بالتنفيذ عن بعد)
- 🟡 مهم (يكشف معلومات)
- 🟢 بسيط (ممارسات سيئة)
""",
            "architecture-review": """# Architecture Review Skill

## الغرض
مراجعة معمارية الكود.

## المحاور
1. فصل المسؤوليات (SRP)
2. الترابط (Coupling) والتماسك (Cohesion)
3. نمط المعمارية (MVVM, MVC, Clean)
4. قابلية الاختبار
5. قابلية التوسع

## المخرجات
- 3 نقاط قوة معمارية
- 3 مشاكل معمارية
- 3 توصيات معمارية
""",
            "documentation": """# Documentation Skill

## الغرض
كتابة توثيق احترافي.

## الأقسام
1. نظرة عامة
2. التثبيت
3. الاستخدام السريع
4. أمثلة متقدمة
5. الأسئلة الشائعة
6. المساهمة

## القواعد
- ابدأ بالاستخدام، لا بالمعمارية
- أمثلة قابلة للنسخ
- عربية واضحة + إنجليزية تقنية
""",
            "testing": """# Testing Skill

## الغرض
كتابة اختبارات شاملة.

## الهرم
- Unit (70%): اختبار كل دالة
- Integration (25%): اختبار التكامل
- E2E (5%): سيناريوهات كاملة

## لكل اختبار
- اسم واضح (test_what_when_then)
- Arrange / Act / Assert
- لا mocks للكود الذي تختبره
""",
        }
        for name, content in defaults.items():
            skill_dir = self.base_dir / name
            skill_dir.mkdir(exist_ok=True)
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                skill_file.write_text(content, encoding="utf-8")

    def list(self) -> list[str]:
        """يعيد قائمة بأسماء المهارات."""
        return sorted(
            d.name for d in self.base_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
        )

    def load(self, name: str) -> Skill | None:
        """يحمّل مهارة بالاسم."""
        skill_file = self.base_dir / name / "SKILL.md"
        if not skill_file.exists():
            return None
        content = skill_file.read_text(encoding="utf-8")
        description = ""
        for line in content.split("\n"):
            if line.startswith("#"):
                description = line.lstrip("#").strip()
                break
        return Skill(
            name=name,
            description=description,
            content=content,
            path=skill_file,
        )

    def search(self, query: str) -> list[Skill]:
        """يبحث في المهارات."""
        q = query.lower()
        results: list[Skill] = []
        for name in self.list():
            skill = self.load(name)
            if skill and (q in skill.name.lower() or q in skill.content.lower()):
                results.append(skill)
        return results
