"""Smart Router — يقرر: وكيل واحد أم فريق، من يشارك، وكيف."""
from __future__ import annotations
import os
import sys
import re
from dataclasses import dataclass
from enum import StrEnum

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))


class Complexity(StrEnum):
    SIMPLE = "simple"      # وكيل واحد
    STANDARD = "standard"  # 2-3 وكلاء
    COMPLEX = "complex"    # 4+ وكلاء
    CRITICAL = "critical"  # Council


class Strategy(StrEnum):
    SINGLE = "single"      # وكيل واحد
    SEQUENTIAL = "sequential"  # متسلسل
    PARALLEL = "parallel"  # متوازي (Fanout)
    COUNCIL = "council"    # مجلس


@dataclass
class RouteDecision:
    """قرار التوجيه."""
    strategy: str
    complexity: str
    category: str
    agents: list
    reason: str
    risk_level: str = "low"
    estimated_time: float = 0.0
    council_needed: bool = False


# ═══ أنماط كشف الفئة ═══
CATEGORY_PATTERNS = {
    "code_generation": [
        r"\b(اكتب|أنشئ|create|write|build|implement|generate)\b.*\b(دالة|كود|function|code|class|script)\b",
        r"\b(أضف ميزة|add feature|new module)\b",
    ],
    "bug_fix": [
        r"\b(أصلح|صلح|fix|repair|debug)\b",
        r"\b(خطأ|error|bug|issue|مشكلة)\b.*\b(في|in)\b",
    ],
    "code_review": [
        r"\b(راجع|review|audit|افحص)\b.*\b(كود|code|ملف|file)\b",
        r"\b(جودة|quality|clean)\b",
    ],
    "security": [
        r"\b(أمني|أمنية|أمن|security|secure|حماية|protect)\w*",
        r"\b(ثغرة|ثغرات|vulnerability|vulnerabilities|exploit|attack|هجوم|اختراق)\w*",
        r"\b(password|كلمة السر|token|secret|secrets)\w*",
    ],
    "devops": [
        r"\b(نشر|deploy|docker|k8s|kubernetes|terraform|nginx|CI|CD|pipeline)\b",
    ],
    "data": [
        r"\b(بيانات|data|تحليل|analyze|csv|json|sql|database|قاعدة)\b",
    ],
    "research": [
        r"\b(ابحث|research|study|investigate|قارن|compare)\b",
    ],
    "documentation": [
        r"\b(وثّق|document|شرح|explain|README|docstring)\b",
    ],
    "testing": [
        r"\b(اختبر|test|اختبار|pytest|unit test)\b",
    ],
    "refactor": [
        r"\b(أعد هيكلة|refactor|cleanup|حسّن|optimize|simplify)\b",
    ],
    "ui": [
        r"\b(واجهة|ui|ux|design|تصميم|css|html|frontend)\b",
    ],
}


# ═══ فئات الوكلاء (من CATEGORY_AGENTS الموجود) ═══
CATEGORY_TO_AGENTS = {
    "code_generation": ["coder", "architect", "documentation_agent"],
    "bug_fix": ["fixer", "analyzer", "tester", "debugger"],
    "code_review": ["code_review_agent", "performance_agent", "security_agent", "complexity_agent"],
    "security": ["security_agent", "secrets_agent", "injection_agent", "xss_agent", "crypto_agent"],
    "devops": ["docker_agent", "cicd_agent", "k8s_agent", "nginx_agent", "terraform_agent", "monitoring_agent"],
    "data": ["data_scientist", "analyzer", "embedding_agent", "indexing_agent"],
    "research": ["chief_architect", "project_manager", "lead_researcher"],
    "documentation": ["documentation_agent", "technical_writer", "naming_agent"],
    "testing": ["test_generator", "test_runner", "tester"],
    "refactor": ["refactor_agent", "complexity_agent", "duplication_agent", "naming_agent"],
    "ui": ["css_agent", "vue_agent", "rtl_agent", "a11y_agent"],
}


class SmartRouter:
    """يقرر كيف يوجه الطلب."""

    MAX_SINGLE_AGENT_TASK_LEN = 200
    COMPLEX_KEYWORDS = [
        "شامل", "كامل", "كل", "جميع", "بالتفصيل", "معقد",
        "complete", "full", "entire", "comprehensive", "everything",
        "منصة", "نظام", "مشروع", "architecture",
    ]
    CRITICAL_KEYWORDS = [
        "production", "deploy", "حذف", "delete", "database", "قاعدة بيانات",
        "password", "secret", "token", "auth", "مصادقة", "مالي", "financial",
    ]

    def decide(self, prompt: str) -> RouteDecision:
        """يحلل الطلب ويقرر الاستراتيجية."""
        prompt_lower = prompt.lower()

        # ═══ 1. كشف الفئة ═══
        category = self._detect_category(prompt_lower)

        # ═══ 2. تقدير التعقيد ═══
        complexity = self._detect_complexity(prompt_lower, len(prompt))

        # ═══ 3. تقييم الخطورة ═══
        risk = self._detect_risk(prompt_lower)

        # ═══ 4. اختيار الاستراتيجية ═══
        strategy, agents, reason = self._choose_strategy(
            category, complexity, risk, prompt_lower
        )

        # ═══ 5. إذا خطورة عالية → Council ═══
        council_needed = (risk == "high" or complexity == Complexity.CRITICAL.value)

        return RouteDecision(
            strategy=strategy,
            complexity=complexity,
            category=category,
            agents=agents,
            reason=reason,
            risk_level=risk,
            estimated_time=self._estimate_time(strategy, len(agents)),
            council_needed=council_needed,
        )

    def _detect_category(self, text: str) -> str:
        """يكتشف الفئة من النص."""
        # أولوية خاصة للأمان
        security_strong = ["ثغرة", "ثغرات", "اختراق", "exploit", "vulnerability",
                           "injection", "xss", "csrf", "malware", "hack"]
        if sum(1 for k in security_strong if k in text) >= 1:
            return "security"
        
        scores = {}
        for cat, patterns in CATEGORY_PATTERNS.items():
            score = 0
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                score += len(matches)
            if score > 0:
                scores[cat] = score
        if scores:
            return max(scores, key=scores.get)  # type: ignore[arg-type]
        return "code_generation"  # افتراضي

    def _detect_complexity(self, text: str, length: int) -> str:
        """يقيس التعقيد."""
        # CRITICAL أولاً
        if any(k in text for k in self.CRITICAL_KEYWORDS):
            return Complexity.CRITICAL.value

        # COMPLEX
        complex_hits = sum(1 for k in self.COMPLEX_KEYWORDS if k in text)
        if complex_hits >= 2 or length > 500:
            return Complexity.COMPLEX.value

        # STANDARD
        if complex_hits >= 1 or length > self.MAX_SINGLE_AGENT_TASK_LEN:
            return Complexity.STANDARD.value

        return Complexity.SIMPLE.value

    def _detect_risk(self, text: str) -> str:
        """يقيس الخطورة."""
        critical = ["rm -rf", "delete database", "حذف قاعدة", "drop table", "production"]
        if any(k in text for k in critical):
            return "high"

        medium = ["auth", "password", "مصادقة", "secret", "token", "money", "مالي"]
        if any(k in text for k in medium):
            return "medium"

        return "low"

    def _choose_strategy(
        self, category: str, complexity: str, risk: str, text: str
    ) -> tuple[str, list[str], str]:
        """يختار الاستراتيجية والأعضاء."""
        candidates = CATEGORY_TO_AGENTS.get(category, ["coder", "analyzer"])

        if complexity == Complexity.SIMPLE.value and risk == "low":
            return (
                Strategy.SINGLE.value,
                candidates[:1],
                f"طلب بسيط → وكيل واحد ({candidates[0]})"
            )

        if complexity == Complexity.STANDARD.value:
            return (
                Strategy.SEQUENTIAL.value,
                candidates[:2],
                f"طلب متوسط → وكيلان متسلسلان: {candidates[:2]}"
            )

        if complexity == Complexity.COMPLEX.value:
            return (
                Strategy.PARALLEL.value,
                candidates[:4],
                f"طلب معقد → فريق متوازي ({len(candidates[:4])} وكلاء)"
            )

        # CRITICAL → Council
        return (
            Strategy.COUNCIL.value,
            candidates[:3],
            "طلب حرج → مجلس للتحقق"
        )

    def _estimate_time(self, strategy: str, n_agents: int) -> float:
        """يقدر الوقت بالثواني."""
        base = 1.0
        return {
            "single": base,
            "sequential": base * n_agents,
            "parallel": base * 1.5,
            "council": base * 3.0,
        }.get(strategy, base)
