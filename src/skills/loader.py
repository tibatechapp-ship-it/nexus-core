"""Skills Loader — نظام المهارات.

المهارة = ملف SKILL.md في ``<name>/SKILL.md`` (وصف + تعليمات + أمثلة + قواعد).

مجلّدان بمصدرين (كما قاعدة المعرفة):
* **البذرة** ``<repo>/skills`` — المهارات المُشحونة مع المشروع (تأتي مع الاستنساخ).
* **تجاوز المستخدم** ``~/.config/nexus/skills`` — مهارات الشخص نفسه؛ عند تشابه
  الاسم يفوز ملف المستخدم (تَجاوُز بلا تعديل المستودع).

``SkillLoader(base_dir=...)`` وحدها تُبقي السلوك القديم حرفياً: البذرة تُكتب في
``base_dir`` وبلا مجلّد ثانٍ (متوافق مع الاختبارات القائمة).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["DEFAULT_SKILLS", "SEED_DIR", "SKILLS_DIR", "Skill", "SkillLoader"]

#: تجاوز المستخدم (يفوز عند تشابه الاسم).
SKILLS_DIR = Path.home() / ".config" / "nexus" / "skills"

#: مجلّد البذرة داخل المستودع (``<repo>/skills``).
SEED_DIR = Path(__file__).resolve().parents[2] / "skills"

#: المهارات الافتراضية — تُكتب في مجلّد البذرة عند غيابها (لا تُستبدل أبداً).
DEFAULT_SKILLS: dict[str, str] = {
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


@dataclass
class Skill:
    """مهارة واحدة."""
    name: str
    description: str
    content: str
    path: Path


class SkillLoader:
    """يحمّل المهارات من مجلّد البذرة + تجاوز المستخدم.

    ``seed_dir=None`` ← السلوك القديم: كل شيء (بما فيه البذرة) في ``base_dir``.
    ``seed_dir=<repo>/skills`` ← البذرة هناك، و``base_dir`` تجاوز يعلوها.
    """

    def __init__(
        self, base_dir: Path = SKILLS_DIR, seed_dir: Path | None = None
    ) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.seed_dir = Path(seed_dir) if seed_dir is not None else None
        if self.seed_dir is not None:
            self.seed_dir.mkdir(parents=True, exist_ok=True)
        self._seed_defaults()

    def _dirs(self) -> list[Path]:
        """مجلّدات القراءة: تجاوز المستخدم أولاً ثم البذرة (بلا تكرار)."""
        dirs = [self.base_dir]
        if self.seed_dir is not None and self.seed_dir != self.base_dir:
            dirs.append(self.seed_dir)
        return dirs

    def sources(self) -> list[str]:
        """مسارات مجلّدات القراءة (للواجهة/الاختبار)."""
        return [str(folder) for folder in self._dirs()]

    def _seed_defaults(self) -> None:
        """ينشئ المهارات الافتراضية في مجلّد البذرة إن لم توجد."""
        defaults = DEFAULT_SKILLS
        target = self.seed_dir if self.seed_dir is not None else self.base_dir
        for name, content in defaults.items():
            skill_dir = target / name
            skill_dir.mkdir(exist_ok=True)
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                skill_file.write_text(content, encoding="utf-8")

    def list_skills(self) -> list[str]:
        """يعيد أسماء المهارات من المجلّدين (بلا تكرار)."""
        names: set[str] = set()
        for folder in self._dirs():
            for sub in folder.iterdir():
                if sub.is_dir() and (sub / "SKILL.md").exists():
                    names.add(sub.name)
        return sorted(names)

    def load(self, name: str) -> Skill | None:
        """يحمّل مهارة بالاسم؛ تجاوز المستخدم يفوز عند تشابه الاسم."""
        for folder in self._dirs():
            skill_file = folder / name / "SKILL.md"
            if skill_file.exists():
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
        return None

    def search(self, query: str) -> list[Skill]:
        """يبحث في المهارات."""
        q = query.lower()
        results: list[Skill] = []
        for name in self.list_skills():
            skill = self.load(name)
            if skill and (q in skill.name.lower() or q in skill.content.lower()):
                results.append(skill)
        return results
