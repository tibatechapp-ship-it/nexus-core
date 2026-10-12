"""
Task Planner — Intelligent task decomposition and planning.

Part of Proactive Agent Pipeline:
  [Security Gatekeeper] → [Task Planner] → [Executor] → [Pre-Check] → Output

Responsibilities:
- Analyze user request complexity
- Decompose into subtasks
- Select required agents
- Estimate effort and risk
- Generate execution plan

Uses LLM for intelligent planning with fallback to rule-based.
"""
import re
import json
import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger("core.task_planner")


# ═══════════════════════════════════════════════════════
# Enums & Data Classes
# ═══════════════════════════════════════════════════════
class TaskComplexity(str, Enum):
    TRIVIAL = "trivial"      # < 1 min, 1 agent
    SIMPLE = "simple"        # 1-5 min, 1-2 agents
    MODERATE = "moderate"    # 5-15 min, 3-5 agents
    COMPLEX = "complex"      # 15-60 min, 5+ agents
    EPIC = "epic"            # multi-session, 10+ agents


class TaskCategory(str, Enum):
    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    BUG_FIX = "bug_fix"
    REFACTORING = "refactoring"
    TESTING = "testing"
    DOCUMENTATION = "documentation"
    SECURITY = "security"
    PERFORMANCE = "performance"
    DEVOPS = "devops"
    RESEARCH = "research"
    GENERAL = "general"


@dataclass
class SubTask:
    """A single subtask in the plan."""
    id: str
    description: str
    agents: List[str]
    priority: int = 1                # 1=highest
    estimated_minutes: float = 1.0
    dependencies: List[str] = field(default_factory=list)
    status: str = "pending"          # pending|running|done|failed
    result: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class TaskPlan:
    """Complete execution plan."""
    plan_id: str
    original_request: str
    category: str
    complexity: str
    subtasks: List[SubTask]
    risk_level: str = "low"          # low|medium|high|critical
    confidence: float = 0.8
    reasoning: str = ""
    warnings: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "plan_id": self.plan_id,
            "original_request": self.original_request,
            "category": self.category,
            "complexity": self.complexity,
            "subtasks": [s.to_dict() for s in self.subtasks],
            "risk_level": self.risk_level,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "warnings": self.warnings,
            "estimated_total_minutes": sum(s.estimated_minutes for s in self.subtasks),
            "total_subtasks": len(self.subtasks),
        }


# ═══════════════════════════════════════════════════════
# Category Detection (Rule-Based)
# ═══════════════════════════════════════════════════════
CATEGORY_KEYWORDS = {
    TaskCategory.CODE_GENERATION: [
        r"\b(write|create|generate|build|implement|develop|code)\b",
        r"\b(اكتب|أنشئ|ولد|ابنِ|طور|برمج)\b",
        r"\b(function|class|api|endpoint|module|component)\b",
    ],
    TaskCategory.CODE_REVIEW: [
        r"\b(review|analyze|check|audit|examine|inspect)\b",
        r"\b(راجع|حلل|افحص|دقق)\b",
    ],
    TaskCategory.BUG_FIX: [
        r"\b(fix|bug|error|issue|problem|crash|exception)\b",
        r"\b(أصلح|صحح|خطأ|مشكلة|عطل)\b",
    ],
    TaskCategory.REFACTORING: [
        r"\b(refactor|clean|improve|optimize|simplify|restructure)\b",
        r"\b(أعد\s+هيكلة|حسن|نظف|بسّط)\b",
    ],
    TaskCategory.TESTING: [
        r"\b(test|unit\s+test|integration|coverage|mock|assert)\b",
        r"\b(اختبر|اختبار|تغطية)\b",
    ],
    TaskCategory.DOCUMENTATION: [
        r"\b(document|docs|readme|comment|docstring|explain)\b",
        r"\b(وثق|توثيق|شرح|اشرح)\b",
    ],
    TaskCategory.SECURITY: [
        r"\b(security|secure|vulnerability|exploit|encrypt|auth)\b",
        r"\b(أمان|تأمين|ثغرة|تشفير|مصادقة)\b",
    ],
    TaskCategory.PERFORMANCE: [
        r"\b(performance|speed|slow|optimize|latency|throughput)\b",
        r"\b(أداء|سرعة|بطيء|تحسين)\b",
    ],
    TaskCategory.DEVOPS: [
        r"\b(deploy|docker|kubernetes|ci.?cd|pipeline|infrastructure)\b",
        r"\b(انشر|نشر|رفع|بنية\s+تحتية|خادم|سيرفر|production|prod)\b",
        r"\b(deploy\s+to|push\s+to)\s+(prod|production|staging)\b",
    ],
    TaskCategory.RESEARCH: [
        r"\b(research|compare|evaluate|investigate|study)\b",
        r"\b(ابحث|قارن|درس|استكشف)\b",
    ],
}

# Agent selection based on category
CATEGORY_AGENTS = {
    TaskCategory.CODE_GENERATION: ["coder", "architecture", "naming", "documentation"],
    TaskCategory.CODE_REVIEW: ["code_review", "security", "performance", "complexity"],
    TaskCategory.BUG_FIX: ["fixer", "multi_fixer", "analyzer", "tester"],
    TaskCategory.REFACTORING: ["refactor", "complexity", "duplication", "naming"],
    TaskCategory.TESTING: ["test_generator", "test_runner", "tester"],
    TaskCategory.DOCUMENTATION: ["documentation", "arabic"],
    TaskCategory.SECURITY: ["security", "crypto", "secrets", "injection", "xss", "compliance"],
    TaskCategory.PERFORMANCE: ["performance", "complexity", "indexing"],
    TaskCategory.DEVOPS: ["docker", "cicd", "k8s", "nginx", "terraform", "monitoring"],
    TaskCategory.RESEARCH: ["arabic", "documentation"],
    TaskCategory.GENERAL: ["coder", "analyzer"],
}


# ═══════════════════════════════════════════════════════
# Complexity Detection
# ═══════════════════════════════════════════════════════
COMPLEXITY_SIGNALS = {
    TaskComplexity.TRIVIAL: [
        r"^(what|ما|ما\s+هي|ما\s+هو|من|who|how|كيف|لماذا|why|when|متى|where|أين|هل)\b",
        r"\?\s*$",
    ],
    TaskComplexity.COMPLEX: [
        r"\b(full|complete|entire|all|everything|شامل|كامل|جميع|بالكامل|شاملاً|كل)\b",
        r"\b(system|platform|framework|application|منظومة|منصة|نظام)\b",
        r"\b(multi-?file|multiple\s+files|عدة\s+ملفات)\b",
        r"\b(جميع\s+الوكلاء|all\s+agents|كل\s+الوكلاء)\b",
        r"\b(باستخدام\s+جميع|using\s+all)\b",
    ],
    TaskComplexity.EPIC: [
        r"\b(architecture|design\s+document|technical\s+spec)\b",
        r"\b(migrate|rewrite|rebuild|migration)\b",
    ],
}


# ═══════════════════════════════════════════════════════
# Risk Detection
# ═══════════════════════════════════════════════════════
RISK_SIGNALS = {
    "critical": [
        r"\b(delete|remove|drop|truncate)\s+(database|table|production)\b",
        r"\b(deploy|push)\s+to\s+(production|prod)\b",
        r"\b(rm\s+-rf|format)\b",
    ],
    "high": [
        r"\b(production|live|real\s+data|data\s+real)\b",
        r"\b(migrate|migration)\s+(data|database)\b",
        r"\b(financial|payment|money|transaction)\b",
    ],
    "medium": [
        r"\b(api|endpoint|service)\b",
        r"\b(auth|security|password)\b",
        r"\b(database|db|sql)\b",
    ],
    "low": []  # default
}


# ═══════════════════════════════════════════════════════
# Task Planner
# ═══════════════════════════════════════════════════════
class TaskPlanner:
    """Plans tasks before execution."""

    def __init__(self, router=None):
        """
        Args:
            router: Optional LLMRouter for intelligent planning.
                    Falls back to rule-based if None.
        """
        self.router = router
        self._compile_patterns()

    def _compile_patterns(self):
        """Pre-compile all regex patterns."""
        self._category_patterns = {
            cat: [re.compile(p, re.IGNORECASE) for p in patterns]
            for cat, patterns in CATEGORY_KEYWORDS.items()
        }
        self._complexity_patterns = {
            comp: [re.compile(p, re.IGNORECASE) for p in patterns]
            for comp, patterns in COMPLEXITY_SIGNALS.items()
        }
        self._risk_patterns = {
            level: [re.compile(p, re.IGNORECASE) for p in patterns]
            for level, patterns in RISK_SIGNALS.items()
            if patterns
        }

    # ─────────────────────────────────────────────────
    # Detection Methods
    # ─────────────────────────────────────────────────
    def detect_category(self, request: str) -> TaskCategory:
        """Detect task category from request."""
        scores: Dict[TaskCategory, int] = {}
        for cat, patterns in self._category_patterns.items():
            score = sum(1 for p in patterns if p.search(request))
            if score > 0:
                scores[cat] = score
        
        if not scores:
            return TaskCategory.GENERAL
        
        return max(scores, key=scores.get)

    def detect_complexity(self, request: str, code_size: int = 0) -> TaskComplexity:
        """Estimate task complexity."""
        # Check epic first (most specific)
        for pattern in self._complexity_patterns[TaskComplexity.EPIC]:
            if pattern.search(request):
                return TaskComplexity.EPIC
        
        # Check trivial (questions)
        for pattern in self._complexity_patterns[TaskComplexity.TRIVIAL]:
            if pattern.search(request):
                return TaskComplexity.TRIVIAL
        
        # Check complex
        complex_score = sum(
            1 for p in self._complexity_patterns[TaskComplexity.COMPLEX]
            if p.search(request)
        )
        if complex_score >= 2:
            return TaskComplexity.COMPLEX
        
        # Estimate by code size / request length
        if code_size > 500 or len(request) > 500:
            return TaskComplexity.MODERATE
        
        return TaskComplexity.SIMPLE

    def detect_risk(self, request: str) -> str:
        """Detect risk level."""
        for level in ["critical", "high", "medium"]:
            for pattern in self._risk_patterns.get(level, []):
                if pattern.search(request):
                    return level
        return "low"

    # ─────────────────────────────────────────────────
    # Planning
    # ─────────────────────────────────────────────────
    def plan(
        self,
        request: str,
        code: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> TaskPlan:
        """
        Generate execution plan for a request.
        
        Tries LLM-based planning first, falls back to rule-based.
        """
        start = time.time()
        
        # Detect characteristics
        category = self.detect_category(request)
        code_size = len(code) if code else 0
        complexity = self.detect_complexity(request, code_size)
        risk = self.detect_risk(request)
        
        # Try LLM planning if router available
        llm_plan = None
        if self.router:
            llm_plan = self._llm_plan(request, code, category, complexity)
        
        # Build subtasks (LLM or rule-based)
        if llm_plan and llm_plan.get("subtasks"):
            subtasks = self._subtasks_from_llm(llm_plan)
            reasoning = llm_plan.get("reasoning", "LLM-generated plan")
            confidence = llm_plan.get("confidence", 0.85)
        else:
            subtasks = self._rule_based_subtasks(request, category, complexity, code)
            reasoning = f"Rule-based plan for {category.value} ({complexity.value})"
            confidence = 0.7
        
        # Warnings
        warnings = []
        if risk == "critical":
            warnings.append("🔴 CRITICAL: This task may affect production/data safety")
        elif risk == "high":
            warnings.append("🟠 HIGH: Handle with care, review recommended")
        if complexity == TaskComplexity.EPIC:
            warnings.append("📋 EPIC task: Consider breaking into multiple sessions")
        
        # Generate plan ID
        plan_id = f"plan_{int(start)}_{hash(request) % 10000}"
        
        plan = TaskPlan(
            plan_id=plan_id,
            original_request=request[:500],
            category=category.value,
            complexity=complexity.value,
            subtasks=subtasks,
            risk_level=risk,
            confidence=confidence,
            reasoning=reasoning,
            warnings=warnings,
        )
        
        logger.info(
            f"Plan created: {plan_id} | {category.value} | "
            f"{complexity.value} | {len(subtasks)} subtasks | risk={risk}"
        )
        
        return plan

    # ─────────────────────────────────────────────────
    # Rule-Based Subtask Generation
    # ─────────────────────────────────────────────────
    def _rule_based_subtasks(
        self,
        request: str,
        category: TaskCategory,
        complexity: TaskComplexity,
        code: Optional[str] = None,
    ) -> List[SubTask]:
        """Generate subtasks based on rules."""
        subtasks = []
        agents = CATEGORY_AGENTS.get(category, ["coder"])
        
        # Complexity determines how many agents to use
        max_agents = {
            TaskComplexity.TRIVIAL: 1,
            TaskComplexity.SIMPLE: 2,
            TaskComplexity.MODERATE: 4,
            TaskComplexity.COMPLEX: 6,
            TaskComplexity.EPIC: 8,
        }[complexity]
        
        selected_agents = agents[:max_agents]
        
        # Subtask 1: Analysis (always)
        subtasks.append(SubTask(
            id="t1",
            description="Analyze request and gather context",
            agents=["analyzer"],
            priority=1,
            estimated_minutes=0.5,
        ))
        
        # Subtask 2..N: Execute with selected agents
        if code and category in [TaskCategory.CODE_REVIEW, TaskCategory.BUG_FIX, TaskCategory.SECURITY]:
            # Parallel analysis
            subtasks.append(SubTask(
                id="t2",
                description=f"Run {category.value} agents in parallel",
                agents=selected_agents,
                priority=2,
                estimated_minutes=1.0 * len(selected_agents),
                dependencies=["t1"],
            ))
            next_id = 3
        else:
            # Sequential generation
            for i, agent in enumerate(selected_agents, start=2):
                subtasks.append(SubTask(
                    id=f"t{i}",
                    description=f"Execute agent: {agent}",
                    agents=[agent],
                    priority=i,
                    estimated_minutes=1.5,
                    dependencies=[f"t{i-1}"],
                ))
            next_id = len(selected_agents) + 2
        
        # Final: Review (for moderate+)
        if complexity in [TaskComplexity.MODERATE, TaskComplexity.COMPLEX, TaskComplexity.EPIC]:
            subtasks.append(SubTask(
                id=f"t{next_id}",
                description="Review and validate results",
                agents=["code_review", "security"],
                priority=next_id,
                estimated_minutes=2.0,
                dependencies=[s.id for s in subtasks if s.id != "t1"],
            ))
        
        return subtasks

    # ─────────────────────────────────────────────────
    # LLM-Based Planning
    # ─────────────────────────────────────────────────
    def _llm_plan(
        self,
        request: str,
        code: Optional[str],
        category: TaskCategory,
        complexity: TaskComplexity,
    ) -> Optional[Dict]:
        """Use LLM to generate a plan."""
        try:
            prompt = f"""Analyze this task and create an execution plan.

REQUEST: {request}

CATEGORY: {category.value}
COMPLEXITY: {complexity.value}
CODE PROVIDED: {'yes' if code else 'no'}

Available agents:
- coder, fixer, multi_fixer: Code generation/fixing
- analyzer, code_review: Analysis and review
- security, crypto, secrets, injection, xss: Security
- test_generator, test_runner, tester: Testing
- refactor, complexity, duplication: Refactoring
- documentation, arabic: Documentation
- performance, indexing: Performance
- docker, cicd, k8s, nginx, terraform: DevOps

Respond in JSON ONLY:
{{
  "reasoning": "brief explanation",
  "confidence": 0.85,
  "subtasks": [
    {{"description": "...", "agents": ["agent1"], "priority": 1, "estimated_minutes": 1.0, "dependencies": []}}
  ]
}}
"""
            result = self.router.generate_for_task(
                task_type="analysis",
                prompt=prompt,
                system="You are an expert task planner. Output valid JSON only.",
                temperature=0.1,
                max_tokens=1000,
            )
            
            if not result.get("ok"):
                return None
            
            text = result.get("text", "")
            # Extract JSON
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                return json.loads(json_match.group(0))
            return None
        except Exception as e:
            logger.warning(f"LLM planning failed: {e}")
            return None

    def _subtasks_from_llm(self, llm_plan: Dict) -> List[SubTask]:
        """Convert LLM output to SubTask objects."""
        subtasks = []
        for i, st in enumerate(llm_plan.get("subtasks", []), start=1):
            subtasks.append(SubTask(
                id=f"t{i}",
                description=st.get("description", f"Step {i}"),
                agents=st.get("agents", ["coder"]),
                priority=st.get("priority", i),
                estimated_minutes=float(st.get("estimated_minutes", 1.0)),
                dependencies=st.get("dependencies", []),
            ))
        return subtasks

    # ─────────────────────────────────────────────────
    # Utilities
    # ─────────────────────────────────────────────────
    def explain_plan(self, plan: TaskPlan) -> str:
        """Generate human-readable explanation of plan."""
        lines = [
            f"📋 **Task Plan** ({plan.complexity})",
            f"",
            f"**Category:** {plan.category}",
            f"**Risk Level:** {plan.risk_level}",
            f"**Confidence:** {plan.confidence:.0%}",
            f"**Estimated Time:** {sum(s.estimated_minutes for s in plan.subtasks):.1f} min",
            f"**Reasoning:** {plan.reasoning}",
            f"",
        ]
        
        if plan.warnings:
            lines.append("**⚠️ Warnings:**")
            for w in plan.warnings:
                lines.append(f"  - {w}")
            lines.append("")
        
        lines.append(f"**Subtasks ({len(plan.subtasks)}):**")
        for st in plan.subtasks:
            deps = f" (depends: {', '.join(st.dependencies)})" if st.dependencies else ""
            lines.append(
                f"  {st.id}. [{st.priority}] {st.description} "
                f"→ {', '.join(st.agents)} (~{st.estimated_minutes}min){deps}"
            )
        
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════
planner = TaskPlanner()


__all__ = [
    "TaskPlanner",
    "TaskPlan",
    "SubTask",
    "TaskCategory",
    "TaskComplexity",
    "planner",
]
