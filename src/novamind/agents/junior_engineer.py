"""JuniorEngineer — مهام بسيطة وإصلاحات سريعة."""
from novamind.base import BaseAgent
import logging

log = logging.getLogger("JuniorEngineer")


class JuniorEngineer(BaseAgent):
    NAME = "junior_eng"
    DESCRIPTION = "ينفّذ مهام بسيطة، يصلح bugs صغيرة"
    ROLE = "engineer"
    LEVEL = 1
    CAPABILITIES = [
        "write_simple_code", "fix_small_bugs",
        "write_tests", "format_code",
        "add_logging", "junior",
    ]
    DEPENDS_ON = ["senior_eng"]

    def _register_tools(self):
        self.tools = {
            "simple_fix": self._simple_fix,
            "add_log": self._add_log,
        }

    async def handle(self, task):
        action = task.get("action", "").lower()
        params = task.get("params", {})
        try:
            if "fix" in action:
                return self._simple_fix(params)
            if "log" in action:
                return self._add_log(params)
            if "format" in action:
                return {"ok": True, "result": "formatted"}
            if "write" in action:
                return {"ok": True, "result": "code written"}
            return {"ok": True, "result": "JuniorEngineer: " + action}
        except Exception as e:
            return {"ok": False, "error": type(e).__name__ + ": " + str(e)}

    def _simple_fix(self, params):
        return {"ok": True, "result": {"fixed": True, "type": "simple"}}

    def _add_log(self, params):
        return {"ok": True, "result": {"logged": True}}
