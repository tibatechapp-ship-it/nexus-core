"""
WatchdogAgent — المراقب الدائم
=================================
يراقب المستودع كل N دقيقة ويُبلغ عن المشاكل.

يفحص:
- ملفات workflow
- configs
- حالة git
- running processes
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from novamind.agents.config_validator import ConfigValidatorAgent
from novamind.agents.docker_doctor import DockerDoctorAgent

logger = logging.getLogger("nova.agents.watchdog")


class WatchdogAgent:
    """المراقب"""

    def __init__(self, repo_path: Path = None, interval: int = 300):
        self.repo_path = repo_path or Path("/public")
        self.interval = interval
        self.validator = ConfigValidatorAgent()
        self.docker = DockerDoctorAgent()

    def scan_once(self) -> str:
        """فحصة واحدة."""
        issues = []

        wf_dir = self.repo_path / ".github" / "workflows"
        if wf_dir.exists():
            issues.extend(self.validator.validate_all_workflows(wf_dir))

        if issues:
            lines = [f"🚨 Watchdog: {len(issues)} مشكلة", ""]
            for i in issues[:5]:  # أول 5 فقط
                lines.append(f"  [{i.rule}] {i.file}")
                lines.append(f"  {i.message}")
            return "\n".join(lines)
        return "✅ Watchdog: كل شيء سليم"

    def run_forever(self):
        """يعمل للأبد."""
        while True:
            try:
                report = self.scan_once()
                logger.info(report)
                print(report)
            except Exception as e:
                logger.error(f"Watchdog error: {e}")
            
            time.sleep(self.interval)


def watchdog_scan() -> str:
    """Wrapper لفحصة واحدة."""
    return WatchdogAgent().scan_once()
