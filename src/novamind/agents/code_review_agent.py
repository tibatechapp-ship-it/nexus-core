"""
Code Review Agent — Unified reviewer combining all analyzers.
Combines: security + performance + documentation + refactor + analyzer + arabic.
"""
import logging
from typing import Dict, List

logger = logging.getLogger("agents.code_review_agent")


class CodeReviewAgent:
    """Comprehensive code review combining multiple analyzers."""

    def __init__(self):
        self.name = "code_review"
        self._agents = {}

    def _get_agent(self, name: str):
        if name in self._agents:
            return self._agents[name]

        module_map = {
            "security": ("agents.security_agent", "security_agent"),
            "performance": ("agents.performance_agent", "performance_agent"),
            "documentation": ("agents.documentation_agent", "documentation_agent"),
            "refactor": ("agents.refactor_agent", "refactor_agent"),
            "analyzer": ("agents.multilang_analyzer", "multilang_analyzer"),
            "arabic": ("agents.arabic_analyzer", "arabic_analyzer"),
        }

        if name not in module_map:
            self._agents[name] = None
            return None

        module_name, var_name = module_map[name]

        try:
            module = __import__(module_name, fromlist=[var_name])
            agent = getattr(module, var_name)
            self._agents[name] = agent
            return agent
        except (ImportError, AttributeError) as e:
            logger.warning(f"agent '{name}' not available: {e}")
            self._agents[name] = None
            return None

    def review(self, code: str, filename: str = "code.py",
               dimensions: List[str] = None) -> Dict:
        """
        Comprehensive review across dimensions.
        dimensions: ["security", "performance", "documentation",
                     "refactor", "analyzer", "arabic"]
        """
        if dimensions is None:
            dimensions = ["security", "performance",
                          "documentation", "refactor", "analyzer"]

        all_issues = []
        by_dimension = {}
        summary = {}

        for dim in dimensions:
            agent = self._get_agent(dim)
            if not agent:
                summary[dim] = "not_available"
                continue

            try:
                result = agent.analyze(code, filename)

                issues = result.get("issues", [])
                for i in issues:
                    i["dimension"] = dim
                    all_issues.append(i)

                count = len(issues)
                summary[dim] = count
                by_dimension[dim] = {
                    "total": count,
                    "verdict": result.get("verdict", "?"),
                    "ok": result.get("ok", False),
                }
            except Exception as e:
                logger.warning(f"agent '{dim}' error: {e}")
                summary[dim] = f"error: {str(e)[:50]}"
                by_dimension[dim] = {"total": 0, "error": str(e)[:80]}

        # Score
        score = self._compute_score(all_issues)
        verdict = self._compute_verdict(all_issues)

        # Group by severity
        by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        for issue in all_issues:
            sev = issue.get("severity", "info").lower()
            if sev in by_severity:
                by_severity[sev] += 1

        return {
            "ok": verdict == "ok",
            "verdict": verdict,
            "filename": filename,
            "dimensions": dimensions,
            "total_issues": len(all_issues),
            "score": score,
            "by_severity": by_severity,
            "summary": summary,
            "by_dimension": by_dimension,
            "issues": all_issues,
        }

    def _compute_score(self, issues: List[Dict]) -> int:
        """Compute quality score (0-100)."""
        score = 100
        for issue in issues:
            sev = issue.get("severity", "info").lower()
            weights = {
                "critical": 15,
                "high": 8,
                "medium": 3,
                "low": 1,
                "info": 0.5,
            }
            score -= weights.get(sev, 1)
        return max(0, int(score))

    def _compute_verdict(self, issues: List[Dict]) -> str:
        """Compute verdict."""
        if any(i.get("severity") == "critical" for i in issues):
            return "broken"
        if any(i.get("severity") == "high" for i in issues):
            return "issues"
        if issues:
            return "warnings"
        return "ok"

    def report(self, result: Dict) -> str:
        """Generate comprehensive report."""
        lines = []
        lines.append("=" * 60)
        lines.append(f"📋 تقرير مراجعة شامل — {result['filename']}")
        lines.append("=" * 60)
        lines.append("")

        # Score with visual
        score = result["score"]
        bar_len = 20
        filled = int(score / 100 * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        emoji = "🎯" if score >= 90 else "⚠️ " if score >= 70 else "🚨"
        lines.append(f"{emoji} النتيجة: {score}/100  [{bar}]")
        lines.append(f"📊 الإجمالي: {result['total_issues']} مشكلة")
        lines.append(f"🏷️  الحكم: {result['verdict']}")
        lines.append("")

        # By dimension
        lines.append("📂 الأبعاد:")
        icons = {
            "security": "🔒",
            "performance": "⚡",
            "documentation": "📚",
            "refactor": "♻️",
            "analyzer": "🔍",
            "arabic": "🌍",
        }
        for dim, count in result.get("summary", {}).items():
            icon = icons.get(dim, "•")
            if isinstance(count, int):
                status = "✅" if count == 0 else f"⚠️  {count}"
                lines.append(f"   {icon} {dim:15s} {status}")
            else:
                lines.append(f"   {icon} {dim:15s} {count}")
        lines.append("")

        # By severity
        by_sev = result.get("by_severity", {})
        if any(by_sev.values()):
            lines.append("⚠️  حسب الخطورة:")
            sev_icons = {
                "critical": "🚨",
                "high": "🔴",
                "medium": "🟡",
                "low": "🔵",
                "info": "ℹ️ ",
            }
            for sev, count in by_sev.items():
                if count > 0:
                    lines.append(f"   {sev_icons.get(sev, '•')} {sev:10s}: {count}")
            lines.append("")

        # Top issues
        priority = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        sorted_issues = sorted(
            result["issues"],
            key=lambda x: priority.get(x.get("severity", "info"), 5),
        )

        if sorted_issues:
            lines.append("🔝 أهم المشاكل:")
            for issue in sorted_issues[:10]:
                dim = issue.get("dimension", "?")
                line_num = issue.get("line", "?")
                desc = issue.get("description", "")[:70]
                lines.append(f"   • [{dim}] L{line_num}: {desc}")

        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)

    def available_dimensions(self) -> List[str]:
        """Return list of available dimensions."""
        all_dims = ["security", "performance", "documentation",
                    "refactor", "analyzer", "arabic"]
        return [d for d in all_dims if self._get_agent(d) is not None]


code_review_agent = CodeReviewAgent()
__all__ = ["CodeReviewAgent", "code_review_agent"]
