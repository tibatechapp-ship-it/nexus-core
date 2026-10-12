"""
AlertBotAgent — وكيل التنبيهات الاستباقية
============================================
يراقب النظام ويُنبّه فوراً عند أي خلل.

قنوات التنبيه:
- Telegram
- Webhook
- File log
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nova.agents.alert_bot")

TELEGRAM_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TELEGRAM_CHAT = os.getenv("TG_CHAT_ID", "")
ALERT_LOG = os.getenv("NOVA_ALERT_LOG", "/tmp/nova_alerts.jsonl")


@dataclass
class Alert:
    """تنبيه"""
    severity: str  # info, warning, error, critical
    title: str
    message: str
    source: str
    timestamp: str


class AlertBotAgent:
    """وكيل التنبيهات"""

    def __init__(self):
        self.log_file = Path(ALERT_LOG)

    def send(self, alert: Alert) -> bool:
        """يرسل تنبيهاً عبر كل القنوات."""
        # 1. File log
        self._log_to_file(alert)
        
        # 2. Telegram (إذا مُهيّأ)
        if TELEGRAM_TOKEN and TELEGRAM_CHAT:
            self._send_telegram(alert)
        
        # 3. Console
        icon = {"info": "ℹ️", "warning": "⚠️", "error": "❌", "critical": "🚨"}
        print(f"{icon.get(alert.severity, '?')} [{alert.severity.upper()}] "
              f"{alert.title}: {alert.message}")
        
        return True

    def _log_to_file(self, alert: Alert) -> None:
        """يحفظ التنبيه."""
        import json
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_file, "a") as f:
            f.write(json.dumps(alert.__dict__, ensure_ascii=False) + "\n")

    def _send_telegram(self, alert: Alert) -> None:
        """يرسل عبر Telegram."""
        import urllib.request
        icon = {"info": "ℹ️", "warning": "⚠️", "error": "❌", "critical": "🚨"}
        msg = (
            f"{icon.get(alert.severity, '?')} *{alert.title}*\n\n"
            f"{alert.message}\n\n"
            f"`{alert.source}`"
        )
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            data = f"chat_id={TELEGRAM_CHAT}&parse_mode=Markdown&text={msg}"
            req = urllib.request.Request(
                url, data=data.encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            logger.warning(f"Telegram alert failed: {e}")


def alert(severity: str, title: str, message: str, source: str = "system") -> None:
    """Wrapper."""
    AlertBotAgent().send(Alert(
        severity=severity,
        title=title,
        message=message,
        source=source,
        timestamp=datetime.now().isoformat(timespec="seconds"),
    ))
