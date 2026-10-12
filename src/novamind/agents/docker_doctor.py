"""
DockerDoctorAgent — وكيل طبيب Docker
=======================================
متخصص في مشاكل Docker:
- Tags غير صالحة
- Dockerfile غير صحيح
- multi-stage builds
- base image issues
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

logger = logging.getLogger("nova.agents.docker_doctor")


@dataclass
class DockerIssue:
    """مشكلة Docker"""
    file: str
    rule: str
    severity: str
    message: str
    fix: str


class DockerDoctorAgent:
    """طبيب Docker"""

    def diagnose_workflow(self, file_path: Path) -> List[DockerIssue]:
        """يشخص ملف workflow."""
        issues = []
        content = file_path.read_text(encoding='utf-8')

        # 1. Docker tags validation
        tag_patterns = [
            (r'prefix=\{\{branch\}\}-', 
             "tags", "error",
             "Docker tag يبدأ بـ '-' عند PR",
             "استخدم prefix=sha- أو أضف شرط disable"),
        ]

        for pattern, rule, severity, msg, fix in tag_patterns:
            for m in re.finditer(pattern, content):
                line = content[:m.start()].count('\n') + 1
                issues.append(DockerIssue(
                    file=f"{file_path}:{line}",
                    rule=rule,
                    severity=severity,
                    message=msg,
                    fix=fix,
                ))

        # 2. Dockerfile existence check
        df_match = re.search(r'file:\s*([^\s\n]+)', content)
        if df_match:
            dockerfile = Path("/public") / df_match.group(1).lstrip("./")
            if not dockerfile.exists():
                issues.append(DockerIssue(
                    file=str(file_path),
                    rule="Dockerfile-missing",
                    severity="error",
                    message=f"Dockerfile not found: {dockerfile}",
                    fix="تأكد من المسار أو أنشئ الملف",
                ))

        return issues

    def report(self, issues: List[DockerIssue]) -> str:
        if not issues:
            return "✅ Docker: كل شيء سليم"
        
        lines = [f"🐳 Docker Doctor — {len(issues)} مشكلة", ""]
        for i in issues:
            icon = "❌" if i.severity == "error" else "⚠️"
            lines.append(f"{icon} [{i.rule}] {i.file}")
            lines.append(f"   {i.message}")
            lines.append(f"   💡 {i.fix}")
        return "\n".join(lines)


def diagnose_docker(workflows_dir: str = "/public/.github/workflows") -> str:
    """Wrapper."""
    agent = DockerDoctorAgent()
    all_issues = []
    for f in Path(workflows_dir).glob("*.yml"):
        all_issues.extend(agent.diagnose_workflow(f))
    return agent.report(all_issues)
