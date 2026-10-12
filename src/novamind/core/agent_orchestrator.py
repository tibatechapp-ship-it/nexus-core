"""
Agent Orchestrator — Multi-agent workflow coordination.
Enables agents to work together on complex tasks.
"""
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger("core.agent_orchestrator")

from novamind.core.paths import NOVAMIND_HOME as BASE


class AgentMessage:
    """Message between agents."""
    def __init__(self, from_agent: str, to_agent: str, content: Dict,
                 priority: int = 5):
        self.from_agent = from_agent
        self.to_agent = to_agent
        self.content = content
        self.priority = priority
        self.at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict:
        return {
            "from": self.from_agent,
            "to": self.to_agent,
            "content": self.content,
            "priority": self.priority,
            "at": self.at,
        }


class AgentOrchestrator:
    """
    Multi-agent orchestrator.

    Workflow:
    1. Analyzer identifies issues
    2. In parallel: security, performance, docs, refactor
    3. Consensus: pick best candidates
    4. Fixer applies fixes
    5. Reviewer verifies
    6. Reporter generates final report
    """

    def __init__(self):
        self.messages: List[AgentMessage] = []
        self.execution_trace: List[Dict] = []
        self._agents_cache = {}

    def _get_agent(self, name: str):
        if name in self._agents_cache:
            return self._agents_cache[name]

        agent_map = {
            "security": ("agents.security_agent", "security_agent"),
            "performance": ("agents.performance_agent", "performance_agent"),
            "documentation": ("agents.documentation_agent", "documentation_agent"),
            "refactor": ("agents.refactor_agent", "refactor_agent"),
            "code_review": ("agents.code_review_agent", "code_review_agent"),
            "migration": ("agents.migration_agent", "migration_agent"),
            "analyzer": ("agents.multilang_analyzer", "multilang_analyzer"),
            "arabic": ("agents.arabic_analyzer", "arabic_analyzer"),
            "fixer": ("agents.fixer", "fixer_agent"),
            "test_generator": ("agents.test_generator", "test_generator"),
        }

        if name not in agent_map:
            return None

        module_name, var_name = agent_map[name]
        try:
            module = __import__(module_name, fromlist=[var_name])
            agent = getattr(module, var_name)
            self._agents_cache[name] = agent
            return agent
        except (ImportError, AttributeError) as e:
            logger.warning(f"agent '{name}' unavailable: {e}")
            self._agents_cache[name] = None
            return None

    # ═══════════════════════════════════════════════════════
    # Workflow 1: Full Analysis
    # ═══════════════════════════════════════════════════════
    def analyze_full(self, code: str, filename: str = "code.py") -> Dict:
        """
        Comprehensive analysis using all relevant agents.
        """
        trace = []
        t0 = time.time()

        # Use code_review_agent as coordinator
        review_agent = self._get_agent("code_review")
        if not review_agent:
            return {"ok": False, "error": "code_review_agent unavailable"}

        trace.append({"step": "review", "at": datetime.now(timezone.utc).isoformat()})

        dimensions = ["security", "performance", "documentation", "refactor"]
        review_result = review_agent.review(code, filename, dimensions=dimensions)

        # Also run migration
        migration_agent = self._get_agent("migration")
        migration_result = None
        if migration_agent:
            try:
                migration_result = migration_agent.analyze(code, filename)
                trace.append({"step": "migration"})
            except Exception as e:
                logger.warning(f"migration failed: {e}")

        elapsed = time.time() - t0

        return {
            "ok": True,
            "filename": filename,
            "score": review_result.get("score", 100),
            "verdict": review_result.get("verdict", "?"),
            "total_issues": review_result.get("total_issues", 0),
            "review": review_result,
            "migration": migration_result,
            "elapsed_sec": round(elapsed, 3),
            "trace": trace,
        }

    # ═══════════════════════════════════════════════════════
    # Workflow 2: Analyze + Fix + Verify
    # ═══════════════════════════════════════════════════════
    def fix_workflow(self, code: str, filename: str = "code.py",
                     max_iterations: int = 2) -> Dict:
        """
        Full workflow: analyze → fix → verify.
        """
        trace = []
        current_code = code

        for iteration in range(1, max_iterations + 1):
            # Analyze
            analysis = self.analyze_full(current_code, filename)
            if not analysis.get("ok"):
                break

            score = analysis.get("score", 100)
            issues = analysis.get("review", {}).get("issues", [])

            trace.append({
                "iteration": iteration,
                "step": "analyze",
                "score": score,
                "issues": len(issues),
            })

            # If score high enough, stop
            if score >= 80:
                trace.append({
                    "iteration": iteration,
                    "step": "complete",
                    "reason": f"score {score} >= 80",
                })
                break

            # Try to fix critical/high issues
            fixable = [i for i in issues
                       if i.get("severity") in ("critical", "high")]
            if not fixable:
                trace.append({
                    "iteration": iteration,
                    "step": "skip_fix",
                    "reason": "no critical/high issues",
                })
                break

            fixer = self._get_agent("fixer")
            if not fixer:
                trace.append({"step": "skip_fix", "reason": "fixer unavailable"})
                break

            # Apply fix
            try:
                fix_result = fixer.fix(current_code, issues=fixable)
                if fix_result.get("ok"):
                    current_code = fix_result.get("fixed", current_code)
                    trace.append({
                        "iteration": iteration,
                        "step": "fix",
                        "strategy": fix_result.get("strategy"),
                        "change": fix_result.get("change", "")[:100],
                    })
                else:
                    trace.append({
                        "iteration": iteration,
                        "step": "fix_failed",
                        "reason": fix_result.get("reason", "")[:100],
                    })
                    break
            except Exception as e:
                trace.append({
                    "iteration": iteration,
                    "step": "fix_error",
                    "error": str(e)[:100],
                })
                break

        # Final analysis
        final = self.analyze_full(current_code, filename)

        return {
            "ok": True,
            "original_score": analysis.get("score") if 'analysis' in dir() else None,
            "final_score": final.get("score", 100),
            "iterations": len([t for t in trace if t.get("step") == "fix"]),
            "fixed_code": current_code,
            "changed": current_code != code,
            "final_analysis": final,
            "trace": trace,
        }

    # ═══════════════════════════════════════════════════════
    # Workflow 3: Parallel Analysis (fast)
    # ═══════════════════════════════════════════════════════
    def parallel_analyze(self, code: str, filename: str = "code.py") -> Dict:
        """
        Run agents in parallel using ParallelAgentPool.
        """
        try:
            from novamind.agents.parallel_agents import ParallelAgentPool
        except ImportError:
            return self.analyze_full(code, filename)

        # Collect agents
        agents = {}
        for name in ["security", "performance", "documentation", "refactor"]:
            agent = self._get_agent(name)
            if agent:
                agents[name] = lambda a=agent: a.analyze(code, filename)

        if not agents:
            return self.analyze_full(code, filename)

        pool = ParallelAgentPool(agents, timeout=30)
        try:
            results = pool.run_all()
        except Exception as e:
            logger.warning(f"parallel failed: {e}")
            return self.analyze_full(code, filename)

        all_issues = []
        for name, result in results.items():
            if result.get("ok"):
                r = result.get("result", {})
                issues = r.get("issues", [])
                for i in issues:
                    i["dimension"] = name
                all_issues.extend(issues)

        # Compute score
        score = 100
        for issue in all_issues:
            sev = issue.get("severity", "info").lower()
            score -= {"critical": 15, "high": 8, "medium": 3,
                      "low": 1, "info": 0.5}.get(sev, 1)
        score = max(0, int(score))

        return {
            "ok": True,
            "filename": filename,
            "score": score,
            "total_issues": len(all_issues),
            "issues": all_issues,
            "agents_used": list(results.keys()),
            "mode": "parallel",
        }

    # ═══════════════════════════════════════════════════════
    # Stats
    # ═══════════════════════════════════════════════════════
    def stats(self) -> Dict:
        return {
            "available_agents": [
                name for name in [
                    "security", "performance", "documentation",
                    "refactor", "code_review", "migration",
                    "analyzer", "arabic", "fixer", "test_generator",
                ]
                if self._get_agent(name) is not None
            ],
            "messages_processed": len(self.messages),
            "workflows_run": len(self.execution_trace),
        }


# Export
agent_orchestrator = AgentOrchestrator()
__all__ = ["AgentOrchestrator", "AgentMessage", "agent_orchestrator"]
