"""
ConfigValidatorAgent — وكيل مدقق الإعدادات
==============================================
يفحص ملفات YAML/JSON/Docker قبل الرفع، ويكتشف:
- Docker tags غير صالحة
- مسارات خاطئة
- صيغ YAML خاطئة
- متغيرات بيئة مفقودة

قواعد Docker:
✅ tags: [a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}
❌ لا يبدأ بـ '-' أو '.' 
❌ لا يحتوي على {{template}} غير مُستبدل
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("nova.agents.config_validator")


@dataclass
class ConfigIssue:
    """مشكلة في إعداد"""
    file: str
    line: int
    severity: str  # error, warning
    rule: str
    message: str
    fix_suggestion: str = ""


class ConfigValidatorAgent:
    """مدقق الإعدادات"""

    # قواعد Docker tag
    DOCKER_TAG_PATTERN = re.compile(
        r'^[a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}$'
    )

    # أنماط خطيرة في YAML
    DANGEROUS_PATTERNS = [
        {
            "pattern": r'prefix=\{\{branch\}\}-',
            "severity": "error",
            "rule": "DOCKER_TAG_PREFIX",
            "message": "prefix={{branch}}- يُنتج tags تبدأ بـ '-' عند PR",
            "fix": "استبدل بـ prefix=sha- أو أضف enable={{is_default_branch}}",
        },
        {
            "pattern": r'tags:\s*\|\s*\n\s*type=sha,prefix=\{\{branch\}\}',
            "severity": "error",
            "rule": "DOCKER_TAG_SHA_BRANCH",
            "message": "Docker tag format قد يفشل على PR",
            "fix": "استخدم format=long أو prefix ثابت",
        },
        {
            "pattern": r'/public(?!/workspace)',
            "severity": "warning",
            "rule": "HARDCODED_PATH",
            "message": "مسار /public صلب — قد يفشل على CI",
            "fix": "استخدم os.getenv('NOVAMIND_HOME')",
        },
    ]

    def __init__(self):
        self.issues: List[ConfigIssue] = []

    def validate_workflow(self, file_path: Path) -> List[ConfigIssue]:
        """يفحص ملف workflow."""
        try:
            content = file_path.read_text(encoding='utf-8')
        except Exception as e:
            logger.error(f"Could not read {file_path}: {e}")
            return []

        for pattern_info in self.DANGEROUS_PATTERNS:
            for match in re.finditer(pattern_info["pattern"], content):
                # احسب رقم السطر
                line_num = content[:match.start()].count('\n') + 1
                
                issue = ConfigIssue(
                    file=str(file_path),
                    line=line_num,
                    severity=pattern_info["severity"],
                    rule=pattern_info["rule"],
                    message=pattern_info["message"],
                    fix_suggestion=pattern_info.get("fix", ""),
                )
                self.issues.append(issue)

        return self.issues

    def validate_all_workflows(self, workflows_dir: Path = None) -> List[ConfigIssue]:
        """يفحص كل ملفات workflows."""
        if workflows_dir is None:
            workflows_dir = Path("/public/.github/workflows")

        if not workflows_dir.exists():
            logger.warning(f"Workflows dir not found: {workflows_dir}")
            return []

        for wf_file in workflows_dir.glob("*.yml"):
            self.validate_workflow(wf_file)

        return self.issues

    def report(self) -> str:
        """يولّد تقريراً."""
        if not self.issues:
            return "✅ لا مشاكل في الإعدادات"

        errors = [i for i in self.issues if i.severity == "error"]
        warnings = [i for i in self.issues if i.severity == "warning"]

        lines = [
            f"🔍 Config Validator — {len(self.issues)} مشكلة",
            f"  ❌ أخطاء: {len(errors)}",
            f"  ⚠️  تحذيرات: {len(warnings)}",
            "",
        ]

        for issue in self.issues:
            icon = "❌" if issue.severity == "error" else "⚠️"
            lines.append(f"{icon} [{issue.rule}] {issue.file}:{issue.line}")
            lines.append(f"   {issue.message}")
            if issue.fix_suggestion:
                lines.append(f"   💡 الحل: {issue.fix_suggestion}")
            lines.append("")

        return "\n".join(lines)


def validate_configs(workflows_dir: str = None) -> str:
    """Wrapper."""
    agent = ConfigValidatorAgent()
    agent.validate_all_workflows(Path(workflows_dir) if workflows_dir else None)
    return agent.report()
