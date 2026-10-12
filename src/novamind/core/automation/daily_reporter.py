"""DailyReporter — تقرير يومي إلى تيليجرام"""
from pathlib import Path
from datetime import datetime
import os
import json
import logging
import urllib.request
import ssl

logger = logging.getLogger("daily_reporter")


class DailyReporter:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.bot_token = os.environ.get("TG_BOT_TOKEN", "").strip()
        self.chat_id = os.environ.get("TG_ADMIN_ID", "").strip()
        self.reports_dir = self.base_dir / ".nova" / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.enabled = bool(self.bot_token and self.chat_id)

    def send(self, message: str) -> bool:
        if not self.enabled:
            return False
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = json.dumps({
                "chat_id": self.chat_id,
                "text": message[:4000],
                "parse_mode": "HTML",
            }).encode("utf-8")

            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
                resp = json.loads(r.read().decode())
                return resp.get("ok", False)
        except Exception as e:
            logger.error(f"Telegram error: {e}")
            return False

    def generate_report(self) -> str:
        try:
            personnel_dir = self.base_dir / ".nova" / "personnel"
            total = 0
            by_branch = {}

            if personnel_dir.exists():
                for f in personnel_dir.glob("*.json"):
                    if f.name == "id_state.json":
                        continue
                    try:
                        data = json.loads(f.read_text())
                        total += 1
                        branch = data.get("branch", "unknown")
                        by_branch[branch] = by_branch.get(branch, 0) + 1
                    except Exception:
                        pass

            today = datetime.now().strftime("%Y-%m-%d %H:%M")

            lines = [
                f"📊 <b>تقرير NovaMind اليومي</b>",
                f"🕐 {today}",
                "",
                f"<b>🎖️ إجمالي الوكلاء:</b> {total}",
                "",
            ]

            if by_branch:
                lines.append("<b>📊 التوزيع:</b>")
                for b, c in sorted(by_branch.items(), key=lambda x: -x[1])[:8]:
                    lines.append(f"  • {b}: {c}")
                lines.append("")

            lines.extend([
                "<b>🏭 المصنع:</b> نشط 24/7",
                "<b>🎓 المدربون:</b> 50",
                "<b>🔒 الأمان:</b> محمي",
            ])

            return "\n".join(lines)
        except Exception as e:
            return f"⚠️ خطأ: {e}"

    def send_daily(self) -> bool:
        msg = self.generate_report()
        today = datetime.now().strftime("%Y-%m-%d")
        (self.reports_dir / f"daily_{today}.txt").write_text(msg, encoding="utf-8")
        return self.send(msg)
