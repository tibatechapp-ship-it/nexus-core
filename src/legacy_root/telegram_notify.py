"""
Telegram Notifications v2 - Detailed issue reporting
"""
import os
import json
import logging
import sys
import urllib.request
import ssl
from typing import Dict, List, Optional
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("integration.telegram")


class TelegramNotifier:
    def __init__(self, bot_token: str = "", chat_id: str = ""):
        self.bot_token = bot_token
        self.chat_id = chat_id

    @classmethod
    def from_env(cls):
        env_file = Path(os.environ.get("NOVAMIND_HOME", str(Path(__file__).resolve().parent.parent))) / ".env"
        bot_token = ""
        chat_id = ""

        if env_file.exists():
            for line in env_file.read_text().split("\n"):
                line = line.strip()
                if line.startswith("TG_BOT_TOKEN="):
                    bot_token = line.split("=", 1)[1].strip()
                elif line.startswith("TG_ADMIN_ID="):
                    chat_id = line.split("=", 1)[1].strip()

        return cls(bot_token, chat_id)

    def send(self, message: str, parse_mode: str = "Markdown") -> bool:
        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram not configured")
            return False

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": message[:4000],
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }

            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                return resp.status == 200

        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def notify_pr_review(self, repo: str, pr_num: int,
                         files: int, issues: int,
                         issue_details: List[Dict] = None) -> bool:
        """Sends a detailed PR review notification."""
        emoji = "✅" if issues == 0 else "⚠️"

        msg = f"{emoji} *مراجعة PR جديدة*\n\n"
        msg += f"📦 `{repo}`\n"
        msg += f"🔢 PR #{pr_num}\n"
        msg += f"📄 الملفات: `{files}`\n"
        msg += f"🔍 المشاكل: `{issues}`\n"

        # Add detailed issues if provided
        if issue_details and len(issue_details) > 0:
            msg += "\n*تفاصيل المشاكل:*\n"

            # Group by file
            by_file = {}
            for issue in issue_details[:10]:  # Limit to 10
                f = issue.get("filename", "?")
                if f not in by_file:
                    by_file[f] = []
                by_file[f].append(issue)

            for filename, file_issues in list(by_file.items())[:5]:
                short_name = filename.split("/")[-1] if "/" in filename else filename
                msg += f"\n📄 `{short_name}` ({len(file_issues)})\n"
                for issue in file_issues[:3]:
                    line = issue.get("line", "?")
                    desc = issue.get("description", "")[:60]
                    severity = issue.get("severity", "info")
                    icon = {"error": "🔴", "warning": "🟡", "info": "🔵"}.get(severity, "•")
                    msg += f"  {icon} L{line}: {desc}\n"

        msg += f"\n[افتح PR](https://github.com/{repo}/pull/{pr_num})"
        return self.send(msg)

    def notify_fix(self, repo: str, new_pr_url: str, fixes_count: int) -> bool:
        msg = f"🤖 *إصلاح تلقائي جاهز*\n\n"
        msg += f"📦 `{repo}`\n"
        msg += f"✨ عدد الإصلاحات: `{fixes_count}`\n\n"
        msg += f"[افتح PR الإصلاح]({new_pr_url})"
        return self.send(msg)

    def notify_daemon_start(self) -> bool:
        msg = "🚀 *NovaMind Daemon يعمل الآن*\n\n"
        msg += "⏰ يعمل 24/7\n"
        msg += "🔍 يراقب PRs كل 5 دقائق\n"
        msg += "🛠️  يصلح المشاكل تلقائياً\n"
        msg += "🤖 يولّد اختبارات"
        return self.send(msg)

    def notify_error(self, error: str) -> bool:
        return self.send(f"🚨 *خطأ*\n\n`{error[:500]}`")

    def notify_daily_summary(self, stats: Dict) -> bool:
        """Sends a daily summary."""
        msg = "📊 *ملخص اليوم*\n\n"
        msg += f"📄 ملفات: `{stats.get('files', 0)}`\n"
        msg += f"🔍 مشاكل: `{stats.get('issues', 0)}`\n"
        msg += f"✅ PRs مراجعة: `{stats.get('reviewed', 0)}`\n"
        msg += f"🔧 PRs مُصلحة: `{stats.get('fixed', 0)}`\n"
        msg += f"⏱️ تشغيل: `{stats.get('uptime', '0h')}`"
        return self.send(msg)


telegram_notify = TelegramNotifier.from_env()
