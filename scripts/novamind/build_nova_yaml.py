"""
NovaMind — بناء nova.yaml v3 (أسماء قصيرة + aliases + role)
يقرأ من nova.registry_v2.REGISTRY._specs
"""
import sys, re
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, "/public")

import yaml
from nova.registry_v2 import REGISTRY

SHORT_NAME_MAP = {
    "analyzer": "analyzer", "arabic_analyzer": "arabic",
    "multilang_analyzer": "multilang", "a11y_agent": "a11y",
    "agent_builder": "builder", "api_design_agent": "api_design",
    "architect": "architect", "architecture_agent": "architecture",
    "auth_agent": "auth", "chief_architect": "chief_architect",
    "ci_doctor": "ci_doctor", "cicd_agent": "cicd",
    "cleanup_agent": "cleanup", "code_review_agent": "code_review",
    "coder": "coder", "complexity_agent": "complexity",
    "compliance_agent": "compliance", "crypto_agent": "crypto",
    "css_agent": "css", "data_scientist": "data_scientist",
    "db_migration_agent": "db_migration", "deadcode_agent": "deadcode",
    "dependency_agent": "dependency", "devops_engineer": "devops",
    "docker_agent": "docker", "docker_doctor": "docker_doctor",
    "documentation_agent": "documentation", "duplication_agent": "duplication",
    "embedding_agent": "embedding", "evaluation_agent": "evaluation",
    "factory": "factory", "finetune_agent": "finetune",
    "fixer": "fixer", "git_agent": "git",
    "indexing_agent": "indexing", "injection_agent": "injection",
    "k8s_agent": "k8s", "learner": "learner",
    "lead_researcher": "lead_researcher", "maintenance_agent": "maintenance",
    "memory_keeper": "memory_keeper", "migration_agent": "migration",
    "monitoring_agent": "monitoring", "multi_fixer": "multi_fixer",
    "naming_agent": "naming", "nginx_agent": "nginx",
    "nosql_agent": "nosql", "nova_brain": "nova_brain",
    "orm_agent": "orm", "parallel_agents": "parallel",
    "performance_agent": "performance", "precommit_guard": "precommit_guard",
    "privacy_agent": "privacy", "project_manager": "project_manager",
    "prompt_agent": "prompt", "qa_devops": "qa_devops",
    "quality_guardian": "quality_guardian", "react_agent": "react",
    "refactor_agent": "refactor", "rtl_agent": "rtl",
    "secret_scanner": "secret_scanner", "secrets_agent": "secrets",
    "security_agent": "security", "security_engineer": "security_engineer",
    "self_healer": "self_healer", "senior_engineer": "senior",
    "sql_agent": "sql", "technical_writer": "tech_writer",
    "terraform_agent": "terraform", "test_generator": "test_generator",
    "test_runner": "test_runner", "tester": "tester",
    "transaction_agent": "transaction", "vue_agent": "vue",
    "watchdog": "watchdog", "alert_bot": "alert_bot",
    "config_validator": "config_validator", "xss_agent": "xss",
    "junior_engineer": "junior",
}

# ═══ تصنيف الوكلاء: tool vs manager ═══
# Manager = مدير/منسّق، لا يحتاج main_function
MANAGER_AGENTS = {
    # هؤلاء حقاً managers — لا method رئيسي عام:
    "alert_bot", "architect", "chief_architect", "ci_doctor",
    "cleanup", "config_validator", "devops", "docker_doctor",
    "factory", "junior", "lead_researcher", "maintenance",
    "memory_keeper", "precommit_guard", "project_manager",
    "qa_devops", "quality_guardian", "secret_scanner",
    "security_engineer", "self_healer", "tech_writer",
    "nova_brain", "parallel", "watchdog", "data_scientist",
    "senior",
    # ⚠️ coder, fixer, code_review, learner, multi_fixer, test_generator
    # تمت إزالتهم — هم tools ولهم methods (build, fix, review, learn, generate)
}


# ═══ Methods الافتراضية للـ tools التي لا تُعلن main_function ═══
DEFAULT_MAIN_FUNCTIONS = {
    "coder":          "build",
    "fixer":          "fix",
    "multi_fixer":    "fix",
    "code_review":    "review",
    "learner":        "learn",
    "test_generator": "generate",
    "tester":         "run",
    "test_runner":    "run_pytest",
    "git":            "execute",
}


def short_name(long_name: str) -> str:
    if long_name in SHORT_NAME_MAP:
        return SHORT_NAME_MAP[long_name]
    s = re.sub(r"_agent$", "", long_name)
    s = re.sub(r"_analyzer$", "", s)
    return s


print("=" * 70)
print("🏗️  بناء nova.yaml — v3 (role: tool | manager)")
print("=" * 70)

specs = REGISTRY._specs
agents_raw = {}
long_to_short = {}

for long_name, spec in specs.items():
    short = short_name(long_name)
    if short in long_to_short:
        short = f"{short}_2"
    long_to_short[long_name] = short

    aliases = [long_name] if long_name != short else []

    # حدد role
    is_manager = short in MANAGER_AGENTS
    role = "manager" if is_manager else "tool"

    # ═══ main_function: من registry_v2 أو default ═══
    main_fn = spec.main_function
    if main_fn is None and role == "tool":
        main_fn = DEFAULT_MAIN_FUNCTIONS.get(short, "run")

    agents_raw[short] = {
        "module": spec.module,
        "class_name": spec.class_name,
        "main_function": main_fn,
        "role": role,
        "category": spec.category.value if hasattr(spec.category, "value") else str(spec.category),
        "criticality": spec.criticality.value if hasattr(spec.criticality, "value") else str(spec.criticality),
        "capabilities": list(spec.capabilities or []),
        "dependencies": list(spec.dependencies or []),
        "description": spec.description or "",
        "timeout_seconds": spec.timeout_seconds,
        "max_cost_usd": spec.max_cost_usd,
        "aliases": aliases,
    }

print(f"✅ الوكلاء: {len(agents_raw)}")

# Pipelines
from hive.factory.pipeline import PIPELINES
pipelines_raw = {}
for pid, spec in PIPELINES.items():
    if isinstance(spec, dict):
        spec = dict(spec)
        if "agents" in spec:
            spec["agents"] = [long_to_short.get(a, short_name(a)) for a in spec["agents"]]
        pipelines_raw[pid] = spec
    else:
        stages = list(getattr(spec, "stages", []))
        agents_list = [long_to_short.get(a, short_name(a)) for a in getattr(spec, "agents", [])]
        pipelines_raw[pid] = {"stages": stages, "agents": agents_list}

print(f"✅ Pipelines: {len(pipelines_raw)}")

providers_dir = Path("/public/nova/core/providers")
provider_files = sorted([
    f.stem.replace("_provider", "")
    for f in providers_dir.glob("*.py")
    if f.stem not in ("__init__", "orchestrator", "base_app")
])
print(f"✅ Providers: {len(provider_files)}")

categories = sorted({m["category"] for m in agents_raw.values()})
criticalities = sorted({m["criticality"] for m in agents_raw.values()})

alias_map = {}
for name, meta in agents_raw.items():
    for alias in meta.get("aliases", []):
        alias_map[alias] = name

# إحصاءات
tool_count = sum(1 for m in agents_raw.values() if m["role"] == "tool")
manager_count = sum(1 for m in agents_raw.values() if m["role"] == "manager")

unified = {
    "version": "3.0.0",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "generator": "nova/scripts/build_nova_yaml.py",
    "naming_convention": "short (canonical) + aliases (compatibility)",
    "summary": {
        "agents_total": len(agents_raw),
        "tools": tool_count,
        "managers": manager_count,
        "categories": categories,
        "criticalities": criticalities,
        "pipelines": len(pipelines_raw),
        "providers": len(provider_files),
        "aliases_count": len(alias_map),
    },
    "categories": {
        "code": {"description": "كتابة وإصلاح الكود"},
        "security": {"description": "فحص أمني وثغرات"},
        "quality": {"description": "جودة وتحليل ثابت"},
        "infra": {"description": "بنية تحتية ونشر"},
        "data": {"description": "بيانات وقواعد"},
        "ui": {"description": "واجهات أمامية"},
        "research": {"description": "بحث وتخطيط"},
        "meta": {"description": "وكلاء يتعاملون مع الوكلاء"},
    },
    "criticality": {
        "core": {"description": "لا يمكن حذفه — أساسي", "min_count": 1},
        "standard": {"description": "مهم لكن قابل للتعطيل"},
        "optional": {"description": "إضافي"},
    },
    "roles": {
        "tool": {"description": "يُستخدم مباشرة — له main_function"},
        "manager": {"description": "يُدار من الخارج — قد لا يكون له main_function"},
    },
    "agents": agents_raw,
    "alias_index": alias_map,
    "pipelines": pipelines_raw,
    "providers": {"list": provider_files},
}

out_dir = Path("/public/nova/_registry/data")
out_dir.mkdir(parents=True, exist_ok=True)
out_file = out_dir / "nova.yaml"

with open(out_file, "w", encoding="utf-8") as f:
    yaml.safe_dump(
        unified, f, allow_unicode=True, sort_keys=False,
        default_flow_style=False, width=120,
    )

print(f"\n✅ كُتب: {out_file}")
print(f"   الحجم: {out_file.stat().st_size / 1024:.1f} KB")
print(f"\n   Tools:    {tool_count}")
print(f"   Managers: {manager_count}")
print(f"   Aliases:  {len(alias_map)}")
print()
print("🎉 nova.yaml v3 جاهز")
