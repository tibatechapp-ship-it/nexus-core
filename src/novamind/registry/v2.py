"""
NovaMind Unified Registry v2.0
================================
السجل الموحد لجميع وكلاء NovaMind-Hive.

يحتوي على 80 وكيل مصنّفين في 8 فئات:
    CODE, SECURITY, QUALITY, INFRA, DATA, UI, RESEARCH, META

كل وكيل له:
    - name: المعرف الفريد
    - category: التصنيف
    - criticality: core / standard / optional
    - module: مسار الوحدة
    - capabilities: القدرات
    - dependencies: التبعيات
    - description: الوصف

الاستخدام:
    from nova.registry_v2 import REGISTRY, Category, Criticality

    # الإحصائيات
    print(REGISTRY.stats())

    # كل وكلاء CODE
    print(REGISTRY.list_by_category(Category.CODE))

    # الوكلاء الأساسيون
    print(REGISTRY.list_core())

    # تحميل وكيل
    coder = REGISTRY.load_agent("coder")
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Callable

logger = logging.getLogger("novamind.registry_v2")


# ═══════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════

class Category(str, Enum):
    """تصنيفات الوكلاء."""
    CODE = "code"           # كتابة وإصلاح الكود
    SECURITY = "security"   # الأمن
    QUALITY = "quality"     # الجودة والتحليل
    INFRA = "infra"         # البنية التحتية
    DATA = "data"           # البيانات
    UI = "ui"               # واجهات المستخدم
    RESEARCH = "research"   # البحث والتخطيط
    META = "meta"           # الوكلاء الفوقيين


class Criticality(str, Enum):
    """مستوى الأهمية."""
    CORE = "core"           # أساسي — لا يعمل النظام بدونه
    STANDARD = "standard"   # مهم
    OPTIONAL = "optional"   # إضافي


# ═══════════════════════════════════════════════════════════════
# AgentSpec
# ═══════════════════════════════════════════════════════════════

@dataclass
class AgentSpec:
    """مواصفات وكيل واحد."""
    name: str
    category: Category
    criticality: Criticality
    module: str
    class_name: Optional[str] = None
    main_function: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    description: str = ""
    timeout_seconds: int = 120
    max_cost_usd: float = 0.10

    def __post_init__(self):
        # تحويل strings إلى Enums
        if isinstance(self.category, str):
            self.category = Category(self.category)
        if isinstance(self.criticality, str):
            self.criticality = Criticality(self.criticality)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category.value,
            "criticality": self.criticality.value,
            "module": self.module,
            "class_name": self.class_name,
            "main_function": self.main_function,
            "capabilities": self.capabilities,
            "dependencies": self.dependencies,
            "description": self.description,
        }


# ═══════════════════════════════════════════════════════════════
# UnifiedRegistry
# ═══════════════════════════════════════════════════════════════

class UnifiedRegistry:
    """السجل الموحد — 80 وكيل."""

    def __init__(self):
        self._specs: Dict[str, AgentSpec] = {}
        self._by_category: Dict[Category, List[str]] = {
            c: [] for c in Category
        }
        self._by_criticality: Dict[Criticality, List[str]] = {
            c: [] for c in Criticality
        }

    def register(self, spec: AgentSpec) -> None:
        """يُسجّل وكيلاً."""
        if spec.name in self._specs:
            logger.warning(f"⚠️ Overwriting: {spec.name}")
            # إزالة من القوائم القديمة
            old = self._specs[spec.name]
            self._by_category[old.category].remove(spec.name)
            self._by_criticality[old.criticality].remove(spec.name)

        self._specs[spec.name] = spec
        self._by_category[spec.category].append(spec.name)
        self._by_criticality[spec.criticality].append(spec.name)

    def get(self, name: str) -> Optional[AgentSpec]:
        return self._specs.get(name)

    def list_all(self) -> List[str]:
        return sorted(self._specs.keys())

    def list_by_category(self, category: Category) -> List[str]:
        return sorted(self._by_category.get(category, []))

    def list_by_criticality(self, criticality: Criticality) -> List[str]:
        return sorted(self._by_criticality.get(criticality, []))

    def list_core(self) -> List[str]:
        return self.list_by_criticality(Criticality.CORE)

    def has(self, name: str) -> bool:
        return name in self._specs

    def __len__(self) -> int:
        return len(self._specs)

    def __contains__(self, name: str) -> bool:
        return name in self._specs

    def __iter__(self):
        return iter(self._specs.values())

    def stats(self) -> Dict[str, Any]:
        """إحصائيات شاملة."""
        return {
            "total": len(self._specs),
            "by_category": {
                c.value: len(self._by_category[c]) for c in Category
            },
            "by_criticality": {
                c.value: len(self._by_criticality[c]) for c in Criticality
            },
            "core_agents": self.list_core(),
        }

    def validate(self) -> Dict[str, List[str]]:
        """يتحقق من أن كل وكيل يمكن استيراده."""
        errors = []
        missing_modules = []
        missing_attrs = []

        for name, spec in self._specs.items():
            try:
                mod = importlib.import_module(spec.module)
            except ImportError as e:
                missing_modules.append(f"{name}: {spec.module} — {e}")
                continue
            except Exception as e:
                missing_modules.append(f"{name}: {spec.module} — {type(e).__name__}: {e}")
                continue

            if spec.class_name and not hasattr(mod, spec.class_name):
                missing_attrs.append(
                    f"{name}: {spec.module}.{spec.class_name} not found"
                )
            # main_function عادة method على class، لا نتحقق منه

        return {
            "errors": errors,
            "missing_modules": missing_modules,
            "missing_attrs": missing_attrs,
        }

    def load_agent(self, name: str) -> Any:
        """
        يُحمّل الوكيل فعلياً.
        
        Returns:
            - instance if class_name given
            - function if main_function given
            - module otherwise
        """
        spec = self._specs.get(name)
        if not spec:
            raise KeyError(f"Unknown agent: {name}")

        module = importlib.import_module(spec.module)

        if spec.class_name:
            cls = getattr(module, spec.class_name, None)
            if cls is None:
                raise AttributeError(
                    f"{spec.module}.{spec.class_name} not found"
                )
            return cls()

        if spec.main_function:
            fn = getattr(module, spec.main_function, None)
            if fn is None:
                raise AttributeError(
                    f"{spec.module}.{spec.main_function} not found"
                )
            return fn

        return module


# ═══════════════════════════════════════════════════════════════
# التسجيل الفعلي — 80 وكيل
# ═══════════════════════════════════════════════════════════════

REGISTRY = UnifiedRegistry()


def _register_code_agents() -> None:
    """تسجيل 15 وكيل كود."""
    specs = [
        # (name, class, main_fn, criticality, capabilities, deps, desc)
        ("coder", "CoderAgent", None, Criticality.CORE,
         ["write_code", "refactor", "implement"], ["llm_router"],
         "يكتب كود Python من وصف"),

        ("tester", "Tester", "run", Criticality.CORE,
         ["run_tests", "sandbox"], [],
         "يُشغّل كود في بيئة معزولة"),

        ("fixer", "FixerAgent", None, Criticality.STANDARD,
         ["auto_fix", "multi_strategy"], ["llm_router"],
         "إصلاح متعدد الاستراتيجيات"),

        ("multi_fixer", "MultiFixer", None, Criticality.STANDARD,
         ["parallel_fix"], ["llm_router"],
         "3 استراتيجيات إصلاح متوازية"),

        ("refactor_agent", "RefactorAgent", "analyze", Criticality.STANDARD,
         ["refactor_suggest"], ["llm_router"],
         "يقترح إعادة هيكلة"),

        ("cleanup_agent", "CleanupAgent", None, Criticality.STANDARD,
         ["safe_cleanup"], [],
         "حذف آمن للملفات المؤقتة"),

        ("naming_agent", "NamingAgent", "analyze", Criticality.OPTIONAL,
         ["naming_check"], [],
         "يكتشف تسميات سيئة"),

        ("duplication_agent", "DuplicationAgent", "analyze", Criticality.OPTIONAL,
         ["dr_check"], [],
         "يكتشف تكرار الكود"),

        ("deadcode_agent", "DeadCodeAgent", "analyze", Criticality.OPTIONAL,
         ["deadcode_check"], [],
         "يكتشف الكود الميت"),

        ("complexity_agent", "ComplexityAgent", "analyze", Criticality.OPTIONAL,
         ["complexity_check"], [],
         "يقيس التعقيد الدوري"),

        ("senior_engineer", "SeniorEngineer", "_analyze_patterns", Criticality.STANDARD,
         ["design_patterns"], ["llm_router"],
         "أنماط التصميم"),

        ("junior_engineer", "JuniorEngineer", None, Criticality.OPTIONAL,
         ["simple_tasks"], [],
         "مهام بسيطة"),

        ("code_review_agent", "CodeReviewAgent", None, Criticality.CORE,
         ["unified_review", "security", "performance", "docs"],
         ["security_agent", "performance_agent", "documentation_agent"],
         "مراجعة موحّدة — يجمع كل المحللات"),

        ("test_generator", "TestGenerator", None, Criticality.STANDARD,
         ["generate_tests", "edge_cases"], ["llm_router"],
         "توليد اختبارات"),

        ("test_runner", "TestRunner", "run_pytest", Criticality.CORE,
         ["run_pytest", "coverage"], [],
         "يُشغّل pytest مع coverage"),
    ]

    for name, cls, fn, crit, caps, deps, desc in specs:
        REGISTRY.register(AgentSpec(
            name=name,
            category=Category.CODE,
            criticality=crit,
            module=f"nova.agents.{name}",
            class_name=cls,
            main_function=fn,
            capabilities=caps,
            dependencies=deps,
            description=desc,
        ))


def _register_security_agents() -> None:
    """تسجيل 10 وكلاء أمن."""
    specs = [
        ("security_agent", "SecurityAgent", "analyze", Criticality.CORE,
         ["owasp", "vulnerabilities"], [],
         "فحص ثغرات OWASP"),

        ("security_engineer", "SecurityEngineer", None, Criticality.STANDARD,
         ["threat_modeling", "pentest"], [],
         "threat modeling"),

        ("xss_agent", "XSSAgent", "analyze", Criticality.STANDARD,
         ["xss", "csrf"], [],
         "يكتشف XSS/CSRF"),

        ("injection_agent", "InjectionAgent", "analyze", Criticality.STANDARD,
         ["sql_injection", "nosql_injection"], [],
         "يكتشف SQL/NoSQL injection"),

        ("secrets_agent", "SecretsAgent", "analyze", Criticality.CORE,
         ["hardcoded_secrets"], [],
         "مفاتيح مسربة"),

        ("secret_scanner", "SecretScanner", None, Criticality.CORE,
         ["regex_scan", "no_llm"], [],
         "كاشف محلي بدون LLM"),

        ("privacy_agent", "PrivacyAgent", "analyze", Criticality.STANDARD,
         ["pii", "gdpr"], [],
         "PII/GDPR"),

        ("crypto_agent", "CryptoAgent", "analyze", Criticality.STANDARD,
         ["weak_crypto"], [],
         "تشفير ضعيف"),

        ("compliance_agent", "ComplianceAgent", "analyze", Criticality.STANDARD,
         ["soc2", "iso27001", "hipaa"], [],
         "SOC2/ISO/HIPAA"),

        ("auth_agent", "AuthAgent", "analyze", Criticality.STANDARD,
         ["auth", "authz"], [],
         "مصادقة وتفويض"),
    ]

    for name, cls, fn, crit, caps, deps, desc in specs:
        REGISTRY.register(AgentSpec(
            name=name,
            category=Category.SECURITY,
            criticality=crit,
            module=f"nova.agents.{name}",
            class_name=cls,
            main_function=fn,
            capabilities=caps,
            dependencies=deps,
            description=desc,
        ))


def _register_quality_agents() -> None:
    """تسجيل وكلاء الجودة (12)."""
    specs = [
        ("analyzer", "AnalyzerAgent", "analyze", Criticality.CORE,
         ["static_analysis"], ["llm_router"], "تحليل ثابت"),

        ("arabic_analyzer", "ArabicAnalyzer", "analyze", Criticality.STANDARD,
         ["arabic_check"], [], "تحليل عربي"),

        ("multilang_analyzer", "MultiLangAnalyzer", "analyze", Criticality.STANDARD,
         ["multi_lang"], [], "6 لغات"),

        ("rtl_agent", "RTLAgent", "analyze", Criticality.OPTIONAL,
         ["rtl_check"], [], "RTL/LTR"),

        ("evaluation_agent", "EvaluationAgent", "analyze", Criticality.STANDARD,
         ["llm_eval"], [], "تقييم LLM"),

        ("quality_guardian", "QualityGuardian", None, Criticality.CORE,
         ["quality_standards"], [], "معايير الجودة"),

        ("performance_agent", "PerformanceAgent", "analyze", Criticality.STANDARD,
         ["perf_analysis"], [], "أداء"),

        ("documentation_agent", "DocumentationAgent", "analyze", Criticality.STANDARD,
         ["docs_check"], [], "توثيق تلقائي"),

        ("technical_writer", "TechnicalWriter", None, Criticality.STANDARD,
         ["write_docs"], ["llm_router"], "كتابة تقنية"),

        ("prompt_agent", "PromptAgent", "analyze", Criticality.OPTIONAL,
         ["prompt_eng"], [], "هندسة prompts"),
    ]

    for name, cls, fn, crit, caps, deps, desc in specs:
        REGISTRY.register(AgentSpec(
            name=name,
            category=Category.QUALITY,
            criticality=crit,
            module=f"nova.agents.{name}",
            class_name=cls,
            main_function=fn,
            capabilities=caps,
            dependencies=deps,
            description=desc,
        ))


def _register_infra_agents() -> None:
    """تسجيل 10 وكلاء بنية تحتية."""
    specs = [
        ("cicd_agent", "CICDAgent", "analyze", Criticality.STANDARD,
         ["ci_cd_check"], [], "CI/CD"),
        ("devops_engineer", "DevOpsEngineer", None, Criticality.STANDARD,
         ["deploy", "monitor"], [], "DevOps"),
        ("k8s_agent", "K8sAgent", "analyze", Criticality.STANDARD,
         ["k8s_check"], [], "Kubernetes"),
        ("nginx_agent", "NginxAgent", "analyze", Criticality.OPTIONAL,
         ["nginx_check"], [], "Nginx"),
        ("terraform_agent", "TerraformAgent", "analyze", Criticality.STANDARD,
         ["iac_check"], [], "IaC"),
        ("docker_agent", "DockerAgent", "analyze", Criticality.STANDARD,
         ["dockerfile_check"], [], "Dockerfile"),
        ("migration_agent", "MigrationAgent", "analyze", Criticality.STANDARD,
         ["code_migration"], [], "ترحيل كود"),
        ("db_migration_agent", "DBMigrationAgent", "analyze", Criticality.STANDARD,
         ["db_migration"], [], "DB migration"),
        ("monitoring_agent", "MonitoringAgent", "analyze", Criticality.STANDARD,
         ["observability"], [], "Observability"),
        ("git_agent", "GitAgent", "_run", Criticality.STANDARD,
         ["git_ops"], [], "Git طبيعي"),
    ]

    for name, cls, fn, crit, caps, deps, desc in specs:
        REGISTRY.register(AgentSpec(
            name=name,
            category=Category.INFRA,
            criticality=crit,
            module=f"nova.agents.{name}",
            class_name=cls,
            main_function=fn,
            capabilities=caps,
            dependencies=deps,
            description=desc,
        ))


def _register_data_agents() -> None:
    """تسجيل 10 وكلاء بيانات."""
    specs = [
        ("data_scientist", "DataScientist", "_analyze", Criticality.STANDARD,
         ["data_analysis"], ["llm_router"], "تحليل بيانات"),
        ("sql_agent", "SQLAgent", "analyze", Criticality.STANDARD,
         ["sql_check"], [], "SQL"),
        ("nosql_agent", "NoSQLAgent", "analyze", Criticality.STANDARD,
         ["nosql_check"], [], "NoSQL"),
        ("orm_agent", "ORMAgent", "analyze", Criticality.STANDARD,
         ["orm_check"], [], "ORM"),
        ("transaction_agent", "TransactionAgent", "analyze", Criticality.STANDARD,
         ["acid_check"], [], "ACID"),
        ("embedding_agent", "EmbeddingAgent", "analyze", Criticality.STANDARD,
         ["embedding_check"], [], "Vector search"),
        ("indexing_agent", "IndexingAgent", "analyze", Criticality.STANDARD,
         ["index_check"], [], "فهارس"),
        ("finetune_agent", "FinetuneAgent", "analyze", Criticality.OPTIONAL,
         ["finetune_check"], [], "Fine-tuning"),
        ("learner", "LearnerAgent", None, Criticality.CORE,
         ["feedback_loop", "learning"], [], "تعلّم من التجارب"),
        ("lead_researcher", "LeadResearcher", None, Criticality.STANDARD,
         ["research"], ["llm_router"], "بحث متقدم"),
    ]

    for name, cls, fn, crit, caps, deps, desc in specs:
        REGISTRY.register(AgentSpec(
            name=name,
            category=Category.DATA,
            criticality=crit,
            module=f"nova.agents.{name}",
            class_name=cls,
            main_function=fn,
            capabilities=caps,
            dependencies=deps,
            description=desc,
        ))


def _register_ui_agents() -> None:
    """تسجيل 5 وكلاء واجهات."""
    specs = [
        ("css_agent", "CSSAgent", "analyze", Criticality.OPTIONAL,
         ["css_check"], [], "CSS/Tailwind"),
        ("react_agent", "ReactAgent", "analyze", Criticality.STANDARD,
         ["react_check"], [], "React"),
        ("vue_agent", "VueAgent", "analyze", Criticality.OPTIONAL,
         ["vue_check"], [], "Vue"),
        ("a11y_agent", "A11yAgent", "analyze", Criticality.STANDARD,
         ["accessibility"], [], "WCAG"),
        ("api_design_agent", "APIDesignAgent", "analyze", Criticality.STANDARD,
         ["api_check"], [], "REST/GraphQL"),
    ]

    for name, cls, fn, crit, caps, deps, desc in specs:
        REGISTRY.register(AgentSpec(
            name=name,
            category=Category.UI,
            criticality=crit,
            module=f"nova.agents.{name}",
            class_name=cls,
            main_function=fn,
            capabilities=caps,
            dependencies=deps,
            description=desc,
        ))


def _register_research_agents() -> None:
    """تسجيل 6 وكلاء بحث."""
    specs = [
        ("chief_architect", "ChiefArchitect", "_analyze_requirements", Criticality.CORE,
         ["architecture", "planning"], ["llm_router"], "تخطيط معمارية"),
        ("architect", "Architect", None, Criticality.STANDARD,
         ["decompose"], [], "تفكيك مهام"),
        ("architecture_agent", "ArchitectureAgent", "analyze", Criticality.STANDARD,
         ["solid_check"], [], "SOLID"),
        ("project_manager", "ProjectManager", None, Criticality.CORE,
         ["manage_tasks", "track"], [], "إدارة مهام"),
        ("qa_devops", "QA_DevOps", None, Criticality.STANDARD,
         ["qa_ops"], [], "QA + DevOps"),
    ]

    for name, cls, fn, crit, caps, deps, desc in specs:
        REGISTRY.register(AgentSpec(
            name=name,
            category=Category.RESEARCH,
            criticality=crit,
            module=f"nova.agents.{name}",
            class_name=cls,
            main_function=fn,
            capabilities=caps,
            dependencies=deps,
            description=desc,
        ))


def _register_meta_agents() -> None:
    """تسجيل 14 وكيل meta."""
    specs = [
        # الأساسيون
        ("agent_builder", "AgentBuilder", "analyze", Criticality.CORE,
         ["build_agents"], [], "يبني وكلاء جدد"),
        ("factory", "AgentFactory", None, Criticality.CORE,
         ["factory"], [], "مصنع الوكلاء"),
        ("parallel_agents", "ParallelAgentPool", "run_all", Criticality.CORE,
         ["parallel_exec"], [], "محرّك Async متوازي"),
        ("dependency_agent", "DependencyAgent", "analyze", Criticality.STANDARD,
         ["dep_check"], [], "تبعيات"),

        # الجدد (10)
        ("ci_doctor", "CIDoctorAgent", "analyze_ci_logs", Criticality.CORE,
         ["ci_diagnosis"], [], "تشخيص CI"),
        ("self_healer", "SelfHealerAgent", None, Criticality.CORE,
         ["auto_heal"], [], "معالجة ذاتية"),
        ("memory_keeper", "MemoryKeeperAgent", None, Criticality.CORE,
         ["save_lessons"], [], "حفظ الدروس"),
        ("alert_bot", "AlertBotAgent", None, Criticality.STANDARD,
         ["alerting"], [], "تنبيهات"),
        ("nova_brain", "NovaBrain", "handle_ci_failure", Criticality.CORE,
         ["orchestrate", "coordinate"], ["ci_doctor", "self_healer", "memory_keeper", "alert_bot"],
         "العقل المنسّق 🧠"),
        ("config_validator", "ConfigValidatorAgent", None, Criticality.CORE,
         ["validate_yaml", "validate_docker"], [], "مدقق إعدادات"),
        ("docker_doctor", "DockerDoctorAgent", None, Criticality.STANDARD,
         ["diagnose_docker"], [], "طبيب Docker"),
        ("precommit_guard", "PreCommitGuardAgent", None, Criticality.CORE,
         ["precommit_check"], [], "حارس pre-commit"),
        ("watchdog", "WatchdogAgent", "run_forever", Criticality.STANDARD,
         ["continuous_monitor"], [], "مراقب دائم"),
        ("maintenance_agent", "MaintenanceAgent", None, Criticality.OPTIONAL,
         ["maintenance"], [], "صيانة"),
    ]

    for name, cls, fn, crit, caps, deps, desc in specs:
        REGISTRY.register(AgentSpec(
            name=name,
            category=Category.META,
            criticality=crit,
            module=f"nova.agents.{name}",
            class_name=cls,
            main_function=fn,
            capabilities=caps,
            dependencies=deps,
            description=desc,
        ))


def _register_all() -> None:
    """يُسجّل كل الوكلاء."""
    _register_code_agents()
    _register_security_agents()
    _register_quality_agents()
    _register_infra_agents()
    _register_data_agents()
    _register_ui_agents()
    _register_research_agents()
    _register_meta_agents()


_register_all()


# ═══════════════════════════════════════════════════════════════
# CLI للتشخيص
# ═══════════════════════════════════════════════════════════════

def _cli_main() -> int:
    """تشغيل `python -m nova.registry_v2`."""
    import sys
    import json

    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "stats":
        print(json.dumps(REGISTRY.stats(), indent=2, ensure_ascii=False))
    elif cmd == "validate":
        result = REGISTRY.validate()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1 if (result["missing_modules"] or result["missing_attrs"]) else 0
    elif cmd == "list":
        cat = sys.argv[2] if len(sys.argv) > 2 else None
        if cat:
            names = REGISTRY.list_by_category(Category(cat))
        else:
            names = REGISTRY.list_all()
        for n in names:
            print(f"  {n}")
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python -m nova.registry_v2 [stats|validate|list [category]]")
        return 1

    return 0


__all__ = [
    "Category",
    "Criticality",
    "AgentSpec",
    "UnifiedRegistry",
    "REGISTRY",
]


if __name__ == "__main__":
    import sys
    sys.exit(_cli_main())
