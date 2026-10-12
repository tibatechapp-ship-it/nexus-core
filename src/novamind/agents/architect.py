"""Architect — Decomposes tasks and assigns tools."""
from novamind.base import BaseAgent
import logging

log = logging.getLogger("Architect")

class Architect(BaseAgent):
    NAME = "architect"
    DESCRIPTION = "Decomposes requests into technical specs and tool lists"
    ROLE = "executive"
    LEVEL = 5
    CAPABILITIES = ["decompose_task", "assign_tools", "define_acceptance_criteria"]

    def _register_tools(self):
        self.tools = {}

    async def handle(self, task):
        action = task.get("action", "").lower()
        params = task.get("params", {})
        
        # Ensure we have a request string
        request = params.get("request", "") or params.get("content", "")
        if not request:
            return {"ok": False, "error": "No request provided to Architect"}
        
        if action == "plan":
            # Heuristic Planning Logic
            plan = {
                "objective": request,
                "steps": [
                    {
                        "step": 1, 
                        "agent": "coder", 
                        "task": "write_python_script", 
                        "input": request
                    },
                    {
                        "step": 2, 
                        "agent": "qa_devops", 
                        "task": "review_and_test", 
                        "input": "{{step_1_output}}"
                    }
                ],
                "required_tools": ["python_ast", "file_writer", "sandbox_runner"],
                "acceptance_criteria": "Code runs without error in sandbox"
            }
            
            log.info("Plan Generated with %d steps", len(plan['steps']))
            return {"ok": True, "result": plan}
            
        return {"ok": False, "error": f"Unknown action: {action}"}

# Auto-instance for registry
architect = Architect()
