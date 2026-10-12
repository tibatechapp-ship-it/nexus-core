"""وكيل الصيانة للاختبار."""
import logging
from typing import Dict, Any
from novamind.tools.project_doctor import ProjectDoctor

logger = logging.getLogger("nova.agents.maintenance")

class MaintenanceAgent:
    def check_health(self, task: str = "", ctx: Dict[str, Any] = None) -> Dict[str, Any]:
        ctx = ctx or {}
        root_path = ctx.get("root_path", ".")
        auto_fix = ctx.get("auto_fix", False)
        
        doctor = ProjectDoctor(root=root_path, dry_run=not auto_fix)
        report = doctor.diagnose_and_heal()
        
        criticals = [i for i in report.issues_found if i.severity == "CRITICAL"]
        
        return {
            "ok": len(criticals) == 0,
            "total_issues": len(report.issues_found),
            "critical_count": len(criticals),
            "fixes_applied": len(report.fixes_applied),
            "summary_report": report.summary(),
            "details": [vars(i) for i in report.issues_found]
        }

maintenance_agent = MaintenanceAgent()
