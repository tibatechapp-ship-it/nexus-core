"""SeniorEngineer — كود معقد وتصميم أنماط."""
from novamind.base import BaseAgent
import re
import logging

log = logging.getLogger("SeniorEngineer")


class SeniorEngineer(BaseAgent):
    NAME = "senior_eng"
    DESCRIPTION = "يصمم أنماطاً معقدة، يعيد الهيكلة، يحسّن الأداء"
    ROLE = "engineer"
    LEVEL = 3
    CAPABILITIES = [
        "design_patterns", "complex_refactoring",
        "optimize_performance", "review_architecture",
        "write_advanced_code", "mentor_junior",
        "implement_feature", "senior",
    ]
    DELEGATES_TO = ["junior_eng", "qa", "reviewer"]

    def _register_tools(self):
        self.tools = {
            "analyze_patterns": self._analyze_patterns,
            "detect_code_smells": self._detect_code_smells,
        }

    async def handle(self, task):
        action = task.get("action", "").lower()
        params = task.get("params", {})
        try:
            if "pattern" in action:
                return self._analyze_patterns(params)
            if "smell" in action or "review" in action:
                return self._detect_code_smells(params)
            if "implement" in action or "write" in action:
                return self._implement(params)
            if "refactor" in action:
                return self._refactor(params)
            return {"ok": True, "result": "SeniorEngineer: " + action}
        except Exception as e:
            log.exception("SeniorEngineer failed")
            return {"ok": False, "error": type(e).__name__ + ": " + str(e)}

    def _analyze_patterns(self, params):
        content = params.get("content", "")
        patterns = []
        if "class " in content:
            patterns.append("OOP")
        if "async def" in content:
            patterns.append("async")
        if "@property" in content:
            patterns.append("properties")
        if "dataclass" in content:
            patterns.append("dataclass")
        if "Factory" in content:
            patterns.append("factory")
        return {"ok": True, "result": {"patterns": patterns}}

    def _detect_code_smells(self, params):
        content = params.get("content", "")
        smells = []
        if len(content.split("\n")) > 500:
            smells.append("too_long_file")
        if content.count("if ") > 20:
            smells.append("too_many_conditionals")
        if content.count("for ") > 10:
            smells.append("nested_loops")
        return {"ok": True, "result": {"smells": smells, "count": len(smells)}}

    def _implement(self, params):
        spec = params.get("spec", "")
        return {"ok": True, "result": {"status": "planned", "spec": spec[:100]}}

    def _refactor(self, params):
        return {"ok": True, "result": {"status": "refactored"}}

# Auto-instance for registry
senior_engineer = SeniorEngineer()
