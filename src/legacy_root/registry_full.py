#!/usr/bin/env python3
"""
Hive Factory Registry — Full (67 Agents)
==========================================
يولّد تلقائياً من reports/all_agents_signatures.json
عدد الوكلاء: 66
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger("hive.factory.registry_full")


@dataclass
class AgentSpec:
    """مواصفات وكيل واحد."""
    name: str
    category: str
    module: str
    class_name: str
    method: str
    timeout_seconds: int = 120
    max_cost_usd: float = 0.10
    signature_map: Dict[str, str] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# AGENT_REGISTRY — 66 وكيل
# ═══════════════════════════════════════════════════════════════
AGENT_REGISTRY: Dict[str, AgentSpec] = {

    "a11y_agent": AgentSpec(
        name="a11y_agent",
        category="ui",
        module="nova.agents.a11y_agent",
        class_name="a11y_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "agent_builder": AgentSpec(
        name="agent_builder",
        category="code",
        module="nova.agents.agent_builder",
        class_name="agent_builder",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "analyzer": AgentSpec(
        name="analyzer",
        category="analysis",
        module="nova.agents.analyzer",
        class_name="analyzer",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "api_design_agent": AgentSpec(
        name="api_design_agent",
        category="ui",
        module="nova.agents.api_design_agent",
        class_name="api_design_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "arabic_analyzer": AgentSpec(
        name="arabic_analyzer",
        category="analysis",
        module="nova.agents.arabic_analyzer",
        class_name="arabic_analyzer",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "architect": AgentSpec(
        name="architect",
        category="architecture",
        module="nova.agents.architect",
        class_name="Architect",
        method="handle",
        signature_map={'task': 'task'},
    ),

    "architecture_agent": AgentSpec(
        name="architecture_agent",
        category="architecture",
        module="nova.agents.architecture_agent",
        class_name="architecture_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "auth_agent": AgentSpec(
        name="auth_agent",
        category="security",
        module="nova.agents.auth_agent",
        class_name="auth_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "chief_architect": AgentSpec(
        name="chief_architect",
        category="architecture",
        module="nova.agents.chief_architect",
        class_name="ChiefArchitect",
        method="handle",
        signature_map={'task': 'task'},
    ),

    "cicd_agent": AgentSpec(
        name="cicd_agent",
        category="devops",
        module="nova.agents.cicd_agent",
        class_name="cicd_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "code_review_agent": AgentSpec(
        name="code_review_agent",
        category="code",
        module="nova.agents.code_review_agent",
        class_name="code_review_agent",
        method="review",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "coder": AgentSpec(
        name="coder",
        category="code",
        module="nova.agents.coder",
        class_name="coder",
        method="build",
        signature_map={'task': 'request'},
    ),

    "complexity_agent": AgentSpec(
        name="complexity_agent",
        category="code",
        module="nova.agents.complexity_agent",
        class_name="complexity_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "compliance_agent": AgentSpec(
        name="compliance_agent",
        category="security",
        module="nova.agents.compliance_agent",
        class_name="compliance_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "crypto_agent": AgentSpec(
        name="crypto_agent",
        category="security",
        module="nova.agents.crypto_agent",
        class_name="crypto_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "css_agent": AgentSpec(
        name="css_agent",
        category="ui",
        module="nova.agents.css_agent",
        class_name="css_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "data_scientist": AgentSpec(
        name="data_scientist",
        category="data",
        module="nova.agents.data_scientist",
        class_name="DataScientist",
        method="handle",
        signature_map={'task': 'task'},
    ),

    "db_migration_agent": AgentSpec(
        name="db_migration_agent",
        category="data",
        module="nova.agents.db_migration_agent",
        class_name="db_migration_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "deadcode_agent": AgentSpec(
        name="deadcode_agent",
        category="code",
        module="nova.agents.deadcode_agent",
        class_name="deadcode_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "dependency_agent": AgentSpec(
        name="dependency_agent",
        category="code",
        module="nova.agents.dependency_agent",
        class_name="dependency_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "devops_engineer": AgentSpec(
        name="devops_engineer",
        category="devops",
        module="nova.agents.devops_engineer",
        class_name="DevOpsEngineer",
        method="handle",
        signature_map={'task': 'task'},
    ),

    "docker_agent": AgentSpec(
        name="docker_agent",
        category="devops",
        module="nova.agents.docker_agent",
        class_name="docker_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "documentation_agent": AgentSpec(
        name="documentation_agent",
        category="documentation",
        module="nova.agents.documentation_agent",
        class_name="documentation_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "duplication_agent": AgentSpec(
        name="duplication_agent",
        category="code",
        module="nova.agents.duplication_agent",
        class_name="duplication_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "embedding_agent": AgentSpec(
        name="embedding_agent",
        category="data",
        module="nova.agents.embedding_agent",
        class_name="embedding_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "evaluation_agent": AgentSpec(
        name="evaluation_agent",
        category="testing",
        module="nova.agents.evaluation_agent",
        class_name="evaluation_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "finetune_agent": AgentSpec(
        name="finetune_agent",
        category="data",
        module="nova.agents.finetune_agent",
        class_name="finetune_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "fixer": AgentSpec(
        name="fixer",
        category="code",
        module="nova.agents.fixer",
        class_name="fixer_agent",
        method="fix",
        signature_map={'task': 'code'},
    ),

    "git_agent": AgentSpec(
        name="git_agent",
        category="other",
        module="nova.agents.git_agent",
        class_name="git_agent",
        method="status",
    ),

    "indexing_agent": AgentSpec(
        name="indexing_agent",
        category="data",
        module="nova.agents.indexing_agent",
        class_name="indexing_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "injection_agent": AgentSpec(
        name="injection_agent",
        category="security",
        module="nova.agents.injection_agent",
        class_name="injection_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "junior_engineer": AgentSpec(
        name="junior_engineer",
        category="management",
        module="nova.agents.junior_engineer",
        class_name="JuniorEngineer",
        method="handle",
        signature_map={'task': 'task'},
    ),

    "k8s_agent": AgentSpec(
        name="k8s_agent",
        category="devops",
        module="nova.agents.k8s_agent",
        class_name="k8s_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "lead_researcher": AgentSpec(
        name="lead_researcher",
        category="management",
        module="nova.agents.lead_researcher",
        class_name="LeadResearcher",
        method="handle",
        signature_map={'task': 'task'},
    ),

    "learner": AgentSpec(
        name="learner",
        category="other",
        module="nova.agents.learner",
        class_name="learner_agent",
        method="learn",
        signature_map={'task': 'summary'},
    ),

    "migration_agent": AgentSpec(
        name="migration_agent",
        category="devops",
        module="nova.agents.migration_agent",
        class_name="migration_agent",
        method="detect_lang",
        signature_map={'ctx.filename': 'filename'},
    ),

    "monitoring_agent": AgentSpec(
        name="monitoring_agent",
        category="devops",
        module="nova.agents.monitoring_agent",
        class_name="monitoring_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "multi_fixer": AgentSpec(
        name="multi_fixer",
        category="code",
        module="nova.agents.multi_fixer",
        class_name="multi_fixer",
        method="fix",
        signature_map={'task': 'code'},
    ),

    "multilang_analyzer": AgentSpec(
        name="multilang_analyzer",
        category="analysis",
        module="nova.agents.multilang_analyzer",
        class_name="multilang_analyzer",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "naming_agent": AgentSpec(
        name="naming_agent",
        category="code",
        module="nova.agents.naming_agent",
        class_name="naming_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "nginx_agent": AgentSpec(
        name="nginx_agent",
        category="devops",
        module="nova.agents.nginx_agent",
        class_name="nginx_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "nosql_agent": AgentSpec(
        name="nosql_agent",
        category="data",
        module="nova.agents.nosql_agent",
        class_name="nosql_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "orm_agent": AgentSpec(
        name="orm_agent",
        category="data",
        module="nova.agents.orm_agent",
        class_name="orm_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "parallel_agents": AgentSpec(
        name="parallel_agents",
        category="code",
        module="nova.agents.parallel_agents",
        class_name="Judge",
        method="evaluate",
        signature_map={'task': 'candidate'},
    ),

    "performance_agent": AgentSpec(
        name="performance_agent",
        category="code",
        module="nova.agents.performance_agent",
        class_name="performance_agent",
        method="detect_lang",
        signature_map={'ctx.filename': 'filename'},
    ),

    "privacy_agent": AgentSpec(
        name="privacy_agent",
        category="security",
        module="nova.agents.privacy_agent",
        class_name="privacy_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "project_manager": AgentSpec(
        name="project_manager",
        category="management",
        module="nova.agents.project_manager",
        class_name="ProjectManager",
        method="handle",
        signature_map={'task': 'task'},
    ),

    "prompt_agent": AgentSpec(
        name="prompt_agent",
        category="other",
        module="nova.agents.prompt_agent",
        class_name="prompt_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "qa_devops": AgentSpec(
        name="qa_devops",
        category="testing",
        module="nova.agents.qa_devops",
        class_name="QA_DevOps",
        method="handle",
        signature_map={'task': 'task'},
    ),

    "quality_guardian": AgentSpec(
        name="quality_guardian",
        category="other",
        module="nova.agents.quality_guardian",
        class_name="QualityGuardian",
        method="handle",
        signature_map={'task': 'task'},
    ),

    "react_agent": AgentSpec(
        name="react_agent",
        category="ui",
        module="nova.agents.react_agent",
        class_name="react_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "refactor_agent": AgentSpec(
        name="refactor_agent",
        category="code",
        module="nova.agents.refactor_agent",
        class_name="refactor_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "rtl_agent": AgentSpec(
        name="rtl_agent",
        category="ui",
        module="nova.agents.rtl_agent",
        class_name="rtl_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "secrets_agent": AgentSpec(
        name="secrets_agent",
        category="security",
        module="nova.agents.secrets_agent",
        class_name="secrets_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "security_agent": AgentSpec(
        name="security_agent",
        category="security",
        module="nova.agents.security_agent",
        class_name="security_agent",
        method="detect_lang",
        signature_map={'ctx.filename': 'filename'},
    ),

    "security_engineer": AgentSpec(
        name="security_engineer",
        category="security",
        module="nova.agents.security_engineer",
        class_name="SecurityEngineer",
        method="handle",
        signature_map={'task': 'task'},
    ),

    "senior_engineer": AgentSpec(
        name="senior_engineer",
        category="management",
        module="nova.agents.senior_engineer",
        class_name="SeniorEngineer",
        method="handle",
        signature_map={'task': 'task'},
    ),

    "sql_agent": AgentSpec(
        name="sql_agent",
        category="data",
        module="nova.agents.sql_agent",
        class_name="sql_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "technical_writer": AgentSpec(
        name="technical_writer",
        category="documentation",
        module="nova.agents.technical_writer",
        class_name="TechnicalWriter",
        method="handle",
        signature_map={'task': 'task'},
    ),

    "terraform_agent": AgentSpec(
        name="terraform_agent",
        category="devops",
        module="nova.agents.terraform_agent",
        class_name="terraform_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "test_generator": AgentSpec(
        name="test_generator",
        category="testing",
        module="nova.agents.test_generator",
        class_name="test_generator",
        method="generate",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "test_runner": AgentSpec(
        name="test_runner",
        category="testing",
        module="nova.agents.test_runner",
        class_name="test_runner",
        method="run_pytest",
        signature_map={'task': 'test_code'},
    ),

    "tester": AgentSpec(
        name="tester",
        category="testing",
        module="nova.agents.tester",
        class_name="tester",
        method="run",
        signature_map={'task': 'code'},
    ),

    "transaction_agent": AgentSpec(
        name="transaction_agent",
        category="other",
        module="nova.agents.transaction_agent",
        class_name="transaction_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "vue_agent": AgentSpec(
        name="vue_agent",
        category="ui",
        module="nova.agents.vue_agent",
        class_name="vue_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

    "xss_agent": AgentSpec(
        name="xss_agent",
        category="security",
        module="nova.agents.xss_agent",
        class_name="xss_agent",
        method="analyze",
        signature_map={'task': 'code', 'ctx.filename': 'filename'},
    ),

}


# ═══════════════════════════════════════════════════════════════
# Stats
# ═══════════════════════════════════════════════════════════════
def get_stats() -> Dict[str, Any]:
    """إحصائيات السجل."""
    by_cat: Dict[str, int] = {}
    for spec in AGENT_REGISTRY.values():
        by_cat[spec.category] = by_cat.get(spec.category, 0) + 1
    return {
        "total": len(AGENT_REGISTRY),
        "categories": len(by_cat),
        "by_category": by_cat,
    }


if __name__ == "__main__":
    import json
    print("=" * 70)
    print("📋 Full Registry — 66 وكيل")
    print("=" * 70)
    stats = get_stats()
    print(f"\n📊 إجمالي: {stats['total']}")
    print(f"📁 الفئات: {stats['categories']}\n")
    for cat, count in sorted(stats["by_category"].items()):
        print(f"   • {cat:20s}: {count}")