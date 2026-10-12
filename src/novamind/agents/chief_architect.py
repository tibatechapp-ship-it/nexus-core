"""ChiefArchitect — يخطط المعمارية ويتخذ القرارات."""
from novamind.base import BaseAgent
import json
import re
import logging

log = logging.getLogger("ChiefArchitect")


class ChiefArchitect(BaseAgent):
    NAME = "architect"
    DESCRIPTION = "يخطط المعمارية، يقسّم المهام، يتخذ القرارات"
    ROLE = "executive"
    LEVEL = 5
    CAPABILITIES = [
        "plan_architecture", "design_system",
        "choose_technology", "review_design",
        "break_down_task", "estimate_effort",
        "analyze_requirements", "create_plan",
        "decompose", "architect",
    ]
    DELEGATES_TO = ["researcher", "senior_eng", "techwriter"]

    def _register_tools(self):
        self.tools = {
            "analyze_requirements": self._analyze_requirements,
            "decompose_task": self._decompose_task,
            "estimate": self._estimate,
        }

    async def handle(self, task):
        action = task.get("action", "").lower()
        params = task.get("params", {})

        try:
            if "plan" in action or "decompose" in action or "break" in action:
                return self._decompose_task(params)

            if "analyze" in action or "requirement" in action:
                return self._analyze_requirements(params)

            if "estimate" in action:
                return self._estimate(params)

            if "design" in action:
                return self._design(params)

            return {"ok": True, "result": f"Architect: {action}"}

        except Exception as e:
            log.exception("ChiefArchitect failed")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def _analyze_requirements(self, params):
        """يحلل المتطلبات."""
        text = params.get("text", "") or params.get("requirements", "")
        if not text:
            return {"ok": False, "error": "no requirements"}

        # تحليل بسيط
        analysis = {
            "raw": text[:500],
            "type": self._classify(text),
            "complexity": self._estimate_complexity(text),
            "estimated_hours": self._estimate_hours(text),
            "required_roles": self._required_roles(text),
        }
        return {"ok": True, "result": analysis}

    def _decompose_task(self, params):
        """يقسّم المهمة إلى مهام فرعية."""
        text = params.get("text", "") or params.get("task", "")
        if not text:
            return {"ok": False, "error": "no task"}

        # قسّم حسب النوع
        task_type = self._classify(text)

        plans = {
            "bug_fix": [
                {"agent": "code", "action": "read_file", "params": {"path": params.get("file", "")}},
                {"agent": "code", "action": "fix_bug", "depends_on": [0]},
                {"agent": "code", "action": "run_pytest", "depends_on": [1]},
                {"agent": "security", "action": "scan_secrets", "depends_on": [1]},
                {"agent": "devops", "action": "git_commit", "depends_on": [2, 3]},
            ],
            "feature": [
                {"agent": "research", "action": "summarize", "params": {"text": text}},
                {"agent": "code", "action": "write_code", "depends_on": [0]},
                {"agent": "code", "action": "run_pytest", "depends_on": [1]},
                {"agent": "writer", "action": "write_docs", "depends_on": [1]},
                {"agent": "devops", "action": "git_commit", "depends_on": [2, 3]},
            ],
            "audit": [
                {"agent": "security", "action": "scan_secrets", "params": {"path": "/public"}},
                {"agent": "security", "action": "check_permissions", "depends_on": [0]},
                {"agent": "analysis", "action": "compute_stats", "depends_on": [0, 1]},
                {"agent": "writer", "action": "write", "depends_on": [2]},
            ],
            "documentation": [
                {"agent": "code", "action": "list_dir", "params": {"path": "/public"}},
                {"agent": "writer", "action": "write", "depends_on": [0]},
                {"agent": "devops", "action": "git_commit", "depends_on": [1]},
            ],
        }

        plan = plans.get(task_type, plans["feature"])
        return {
            "ok": True,
            "result": {
                "task_type": task_type,
                "plan": plan,
                "steps": len(plan),
            },
        }

    def _estimate(self, params):
        """يقدّر الجهد."""
        text = params.get("text", "")
        return {
            "ok": True,
            "result": {
                "complexity": self._estimate_complexity(text),
                "hours": self._estimate_hours(text),
                "risk": self._estimate_risk(text),
            },
        }

    def _design(self, params):
        """يصمّم نظام."""
        text = params.get("text", "")
        return {
            "ok": True,
            "result": {
                "approach": "modular",
                "components": ["core", "api", "storage"],
                "tech_stack": ["python", "aiohttp"],
                "notes": f"design for: {text[:100]}",
            },
        }

    # ═══ Helpers ═══
    def _classify(self, text: str) -> str:
        t = text.lower()
        if "bug" in t or "أصلح" in t or "fix" in t:
            return "bug_fix"
        if "feature" in t or "أضف" in t or "add" in t:
            return "feature"
        if "audit" in t or "مراجعة" in t or "security" in t:
            return "audit"
        if "doc" in t or "توثيق" in t:
            return "documentation"
        return "feature"

    def _estimate_complexity(self, text: str) -> str:
        n = len(text)
        if n > 500:
            return "high"
        if n > 200:
            return "medium"
        return "low"

    def _estimate_hours(self, text: str) -> float:
        complexity = self._estimate_complexity(text)
        return {"low": 0.5, "medium": 2.0, "high": 8.0}[complexity]

    def _estimate_risk(self, text: str) -> str:
        t = text.lower()
        if "delete" in t or "remove" in t or "حذف" in t:
            return "high"
        if "refactor" in t or "rewrite" in t:
            return "medium"
        return "low"

    def _required_roles(self, text: str) -> list:
        task_type = self._classify(text)
        return {
            "bug_fix": ["engineer", "quality"],
            "feature": ["researcher", "engineer", "quality", "writer"],
            "audit": ["security", "researcher", "writer"],
            "documentation": ["writer"],
        }.get(task_type, ["engineer"])

# Auto-instance for registry
chief_architect = ChiefArchitect()
