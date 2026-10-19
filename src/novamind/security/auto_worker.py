"""Auto-Worker — يعالج مشاكل الفحص تلقائياً."""
import asyncio
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
import logging

log = logging.getLogger("AutoWorker")



# ═══ تحميل .env عند البدء ═══
def _load_env():
    """يحمل .env في متغيرات البيئة."""
    from pathlib import Path
    env_file = Path("/public/.env")
    if not env_file.exists():
        return
    for line in env_file.read_text().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and v:
            os.environ[k] = v


# حمّل عند الاستيراد
_load_env()

class AutoWorker:
    """يعمل 24/7 لمعالجة مشاكل GitHub تلقائياً."""

    def __init__(self, check_interval: int = 1800):
        """
        Args:
            check_interval: فترة الفحص بالثواني (افتراضي 30 دقيقة)
        """
        self.check_interval = check_interval
        self.state_file = self._state_path()
        self.state = self._load_state()
        self.running = True

    @staticmethod
    def _state_path() -> Path:
        """مسار الحالة على جذر قابل للكتابة (انظر novamind.paths)."""
        override = os.environ.get("NEXUS_AUTO_WORKER_STATE")
        if override:
            return Path(override)
        from ..paths import writable_path

        return writable_path(
            "auto_worker_state.json",
            preferred=("/var/log/novamind", "/var/tmp/novamind"),
        )

    def _load_state(self) -> dict:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except Exception:
                pass
        return {
            "last_check": None,
            "issues_created": 0,
            "issues_closed": 0,
            "reports_sent": 0,
            "failures_handled": 0,
        }

    def _save_state(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.state, indent=2))

    async def run(self):
        """الحلقة الرئيسية."""
        log.info("🚀 AutoWorker started")
        await self._notify_startup()

        while self.running:
            try:
                await self._scan_and_fix()
                self.state["last_check"] = datetime.now().isoformat()
                self._save_state()
            except Exception as e:
                log.exception("AutoWorker cycle failed")

            await asyncio.sleep(self.check_interval)

    async def _scan_and_fix(self):
        """يفحص ويصلح."""
        log.info("🔍 Scanning GitHub + system...")

        from .specialists.github_agent import GitHubAgent
        from .specialists.monitor_agent import MonitorAgent

        gh = GitHubAgent()
        monitor = MonitorAgent()

        # 1. اقرأ Actions
        ci_result = await gh.handle({
            "action": "list_actions",
            "params": {},
        })

        if not ci_result.get("ok"):
            log.warning(f"Cannot read actions: {ci_result.get('error')}")
            return

        runs = ci_result["result"].get("runs", [])

        # 2. ابحث عن حالات فشل
        failed_runs = [
            r for r in runs
            if r.get("conclusion") == "failure"
            and not self._is_already_handled(r["id"])
        ]

        if not failed_runs:
            log.info("✅ No new failures")
            return

        # 3. عالج كل فشل
        for run in failed_runs:
            await self._handle_failure(run, gh)

        # 4. أرسل تقرير
        await self._send_report(monitor, "failure_report")

    def _is_already_handled(self, run_id: int) -> bool:
        """هل عالجناه من قبل؟"""
        handled = self.state.get("handled_runs", [])
        return run_id in handled

    def _mark_handled(self, run_id: int):
        handled = self.state.setdefault("handled_runs", [])
        handled.append(run_id)
        # احتفظ بآخر 100 فقط
        self.state["handled_runs"] = handled[-100:]

    async def _handle_failure(self, run: dict, gh):
        """يعالج فشل → ينشئ Issue."""
        run_id = run["id"]
        name = run["name"]
        url = run["url"]

        log.warning(f"❌ Failure detected: {name} ({run_id})")

        # أنشئ Issue
        title = f"🚨 CI Failure: {name}"
        body = f"""## فشل تلقائي في CI

**Workflow:** {name}
**Run ID:** `{run_id}`
**رابط:** {url}
**الوقت:** {run.get('created', 'unknown')}

### التفاصيل
- Status: {run.get('status', 'unknown')}
- Conclusion: {run.get('conclusion', 'unknown')}

### الإجراء المقترح
1. راجع السجل في الرابط أعلاه
2. حدّد السبب الجذري
3. اقترح إصلاحاً
4. اربط الإصلاح بهذا Issue

---
_تم إنشاؤه تلقائياً بواسطة Hive Auto-Worker_
"""

        result = await gh.handle({
            "action": "create_issue",
            "params": {
                "title": title,
                "body": body,
                "labels": ["ci-failure", "automated", "needs-triage"],
            },
        })

        if result.get("ok"):
            self.state["issues_created"] += 1
            self.state["failures_handled"] += 1
            self._mark_handled(run_id)
            log.info(f"✅ Issue #{result['result']['number']} created")

            # أرسل إشعار
            await self._send_alert(
                f"🚨 فشل جديد!\n\n"
                f"*{name}*\n"
                f"Issue: #{result['result']['number']}\n"
                f"URL: {url}"
            )

    async def _send_report(self, monitor, kind: str):
        """يرسل تقرير."""
        report = await monitor.handle({
            "action": "generate_report",
            "params": {"kind": kind},
        })

        if not report.get("ok"):
            return

        text = report["result"]["text"]
        await self._send_alert(text)
        self.state["reports_sent"] += 1

    async def _send_alert(self, text: str):
        """يرسل رسالة Telegram."""
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID")

        if not token or not chat_id:
            log.warning("Telegram not configured — skipping alert")
            return

        try:
            import urllib.request
            url = f"https://api.telegram.org/bot{token}/sendMessage"

            data = json.dumps({
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }).encode()

            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
            )

            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    log.info("📤 Alert sent")
        except Exception as e:
            log.error(f"Failed to send alert: {e}")

    async def _notify_startup(self):
        """إشعار بدء التشغيل."""
        await self._send_alert(
            "🚀 *Hive Auto-Worker Started*\n\n"
            f"⏱️  فحص كل {self.check_interval // 60} دقيقة\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

    def stop(self):
        self.running = False
        log.info("🛑 AutoWorker stopped")


# ═══ Singleton ═══
_worker = None


def get_auto_worker(interval: int = 1800) -> AutoWorker:
    global _worker
    if _worker is None:
        _worker = AutoWorker(check_interval=interval)
    return _worker


async def run_auto_worker(interval: int = 1800):
    """نقطة دخول."""
    worker = get_auto_worker(interval)
    await worker.run()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    asyncio.run(run_auto_worker())
