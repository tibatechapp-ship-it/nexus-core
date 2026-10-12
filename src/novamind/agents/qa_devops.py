"""QA_DevOps — Tests, Reviews, and Packages code."""
from novamind.base import BaseAgent
from novamind.sandbox import Sandbox 
import os
import logging

log = logging.getLogger("QA_DevOps")

class QA_DevOps(BaseAgent):
    NAME = "qa_devops"
    DESCRIPTION = "Executes tests in sandbox, reviews quality, and generates deployment artifacts"
    ROLE = "quality"
    LEVEL = 4
    CAPABILITIES = ["run_sandbox_test", "security_scan", "generate_dockerfile", "approve_release"]

    def __init__(self):
        # Call parent init first to set up memory/stats
        super().__init__()
        # Initialize Sandbox HERE to guarantee availability
        self.sandbox = Sandbox(timeout=10, max_memory_mb=128)
        self.tools = {
            "test_execution": self._test_execution,
            "create_package": self._create_package,
        }

    async def handle(self, task):
        action = task.get("action", "").lower()
        params = task.get("params", {})
        
        if action == "review_and_test":
            code_content = params.get("code", "")
            file_path = params.get("file_path", "")
            
            # 1. Static Analysis (Security/Style)
            static_issues = self._static_analysis(code_content)
            
            # 2. Dynamic Testing (Sandbox Execution)
            # Determine source: prefer file_path if exists, else use code string
            source_for_test = file_path if file_path and os.path.exists(file_path) else code_content
            
            test_result = await self._test_execution(source_for_test)
            
            # Decision Logic
            passed = test_result.get("ok", False) and len(static_issues) == 0
            
            artifact = None
            if passed:
                artifact = self._create_package(code_content)
                
            return {
                "ok": True,
                "result": {
                    "passed": passed,
                    "static_issues": static_issues,
                    "runtime_output": test_result.get("stdout", ""),
                    "runtime_error": test_result.get("stderr", ""),
                    "deployment_artifact": artifact
                }
            }
            
        return {"ok": False, "error": f"Unknown QA action: {action}"}

    def _static_analysis(self, code: str) -> list:
        issues = []
        if not code: return issues
        if "eval(" in code: issues.append("SECURITY_RISK_EVAL")
        if "os.system(" in code: issues.append("SECURITY_RISK_SYSTEM_CALL")
        if "__import__(" in code: issues.append("SECURITY_RISK_DYNAMIC_IMPORT")
        return issues

    async def _test_execution(self, source: str) -> dict:
        """Runs code in isolated sandbox."""
        if not source:
            return {"ok": False, "error": "Empty Source"}
            
        # If it looks like a path, try reading it, otherwise treat as code string
        code_to_run = source
        if os.path.exists(source):
            try:
                with open(source, 'r') as f:
                    code_to_run = f.read()
            except Exception as e:
                return {"ok": False, "error": f"File Read Error: {e}"}
        
        # Execute in Sandbox
        return self.sandbox.run_python(code_to_run)

    def _create_package(self, code: str) -> dict:
        """Generates a Dockerfile and structure for deployment."""
        dockerfile = """FROM python:3.12-slim
WORKDIR /app
COPY app.py .
CMD ["python", "app.py"]
"""
        return {
            "type": "docker_bundle",
            "files": {
                "Dockerfile": dockerfile,
                "app.py": code
            },
            "instruction": "Run: docker build -t hive-app ."
        }

# Auto-instance for registry
qa_devops = QA_DevOps()
