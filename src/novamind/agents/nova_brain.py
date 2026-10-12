"""
NovaBrain — العقل المنسّق
=============================
يربط الوكلاء الأربعة الجدد ويشغّلهم بشكل متكامل.

Workflow:
1. CIDoctor يقرأ CI logs
2. MemoryKeeper يسترجع الدروس
3. SelfHealer يصلح
4. AlertBot يُنبّه
5. MemoryKeeper يحفظ الدرس الجديد
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from novamind.agents.ci_doctor import CIDoctorAgent
from novamind.agents.self_healer import SelfHealerAgent
from novamind.agents.memory_keeper import MemoryKeeperAgent
from novamind.agents.alert_bot import alert

logger = logging.getLogger("nova.agents.brain")


@dataclass
class BrainReport:
    """تقرير العقل"""
    errors_found: int = 0
    fixes_applied: int = 0
    lessons_recalled: int = 0
    alerts_sent: int = 0
    summary: str = ""


class NovaBrain:
    """العقل المنسّق"""

    def __init__(self, dry_run: bool = True):
        self.ci_doctor = CIDoctorAgent()
        self.healer = SelfHealerAgent(dry_run=dry_run)
        self.memory = MemoryKeeperAgent()
        self.dry_run = dry_run

    def handle_ci_failure(
        self,
        log_text: str,
        job_name: str,
        target_dir: str = "/public",
    ) -> BrainReport:
        """يعالج فشل CI بشكل متكامل."""
        report = BrainReport()
        
        # 1. حلل
        errors = self.ci_doctor.analyze_log(log_text, job_name)
        report.errors_found = len(errors)
        
        if not errors:
            alert("info", "CI", f"{job_name}: لا أخطاء معروفة")
            return report
        
        # 2. استرجع الدروس
        for err in errors:
            lessons = self.memory.recall(err.error_type)
            report.lessons_recalled += len(lessons)
            if lessons:
                logger.info(f"💡 Recalled {len(lessons)} lessons for {err.error_type}")
        
        # 3. أصلح
        fixes = self.healer.heal(Path(target_dir))
        report.fixes_applied = sum(1 for f in fixes if f.ok)
        
        # 4. احفظ الدروس الجديدة
        for err in errors:
            self.memory.remember(
                error_type=err.error_type,
                error_msg=err.message,
                root_cause=err.cause,
                fix=err.fix,
                agent="nova_brain",
            )
        
        # 5. نبّه
        alert(
            severity="error" if not self.dry_run else "warning",
            title=f"CI فشل: {job_name}",
            message=(
                f"أخطاء: {report.errors_found}\n"
                f"إصلاحات: {report.fixes_applied}\n"
                f"دروس: {report.lessons_recalled}"
            ),
            source="nova_brain",
        )
        report.alerts_sent = 1
        
        report.summary = self._generate_summary(report)
        return report

    def _generate_summary(self, r: BrainReport) -> str:
        return (
            f"🧠 NovaBrain Report\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"أخطاء مكتشفة: {r.errors_found}\n"
            f"إصلاحات مطبقة: {r.fixes_applied}\n"
            f"دروس مسترجعة: {r.lessons_recalled}\n"
            f"تنبيهات مرسلة: {r.alerts_sent}\n"
            f"الوضع: {'DRY-RUN' if self.dry_run else 'LIVE'}"
        )


def handle_ci_failure(log_text: str, job_name: str) -> str:
    """Wrapper."""
    brain = NovaBrain(dry_run=True)
    report = brain.handle_ci_failure(log_text, job_name)
    return report.summary
