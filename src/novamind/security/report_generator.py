"""ReportGenerator — Daily Reports."""
import logging
from datetime import datetime

log = logging.getLogger("ReportGenerator")


class ReportGenerator:
    def __init__(self, orch):
        self.orch = orch

    async def generate_daily_report(self):
        status = self.orch.status()
        agents = status.get("agents", {})
        lines = ["# Hive System Report", ""]
        lines.append("**Date:** " + datetime.now().strftime("%Y-%m-%d %H:%M"))
        lines.append("")
        lines.append("## Agents (" + str(len(agents)) + ")")
        lines.append("")
        lines.append("| Agent | Total | Success | Failed |")
        lines.append("|-------|-------|---------|--------|")

        total = success = failed = 0
        for name, info in agents.items():
            s = info.get("stats", {})
            t = s.get("total", 0)
            ok = s.get("success", 0)
            f = s.get("failed", 0)
            total += t
            success += ok
            failed += f
            lines.append("| " + name + " | " + str(t) + " | " + str(ok) + " | " + str(f) + " |")

        lines.append("")
        lines.append("## Summary")
        lines.append("- Total Tasks: " + str(total))
        lines.append("- Successful: " + str(success))
        lines.append("- Failed: " + str(failed))

        return "\n".join(lines)


_gen = None


def get_report_generator(orch):
    global _gen
    if _gen is None:
        _gen = ReportGenerator(orch)
    return _gen
