"""Vixona Report System — Sends complete reports to Telegram.

Handles:
- Long messages (auto-split)
- Retry on failure
- Queue for offline
- Message templates
"""

import os
import sys
import json
import time
import html
import sqlite3
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Optional


# ═══════════════════════════════════════════════
#  Config
# ═══════════════════════════════════════════════

HOME = Path.home()
ENV_FILE = HOME / ".config" / "zyvo" / "telegram.env"
REPORTS_DIR = HOME / "nexus-core" / "reports"
PENDING_DIR = REPORTS_DIR / "pending"
SENT_DIR = REPORTS_DIR / "sent"
FAILED_DIR = REPORTS_DIR / "failed"
DB_PATH = REPORTS_DIR / "reports.db"

MAX_MESSAGE_LENGTH = 4000  # Telegram limit is 4096


def load_env() -> dict:
    """Load telegram.env."""
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                value = value.strip().strip('"').strip("'")
                env[key.strip()] = value
    return env


# ═══════════════════════════════════════════════
#  Database
# ═══════════════════════════════════════════════

def init_db() -> None:
    """Initialize reports database."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            sent_at TEXT,
            status TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            error TEXT
        )
    """)
    conn.commit()
    conn.close()


def log_report(category: str, title: str, content: str, status: str = "pending") -> int:
    """Log a report in the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "INSERT INTO reports (created_at, status, category, title, content) VALUES (?, ?, ?, ?, ?)",
        (datetime.now().isoformat(), status, category, title, content),
    )
    report_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return report_id


def mark_sent(report_id: int, error: Optional[str] = None) -> None:
    """Mark report as sent."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE reports SET sent_at = ?, status = ?, error = ? WHERE id = ?",
        (datetime.now().isoformat(), "sent" if not error else "failed", error, report_id),
    )
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════
#  Message building
# ═══════════════════════════════════════════════

def escape(text: str) -> str:
    """Escape HTML for Telegram."""
    return html.escape(str(text), quote=False)


def build_header(category: str, title: str) -> str:
    """Build message header."""
    icons = {
        "task": "✅",
        "progress": "📈",
        "alert": "🚨",
        "daily": "📋",
        "weekly": "📊",
        "state": "💾",
        "info": "ℹ️",
        "error": "❌",
    }
    icon = icons.get(category, "📌")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"{icon} <b>{escape(title)}</b>\n🕐 {timestamp}\n{'─' * 30}\n"


def split_message(text: str, max_len: int = MAX_MESSAGE_LENGTH) -> list:
    """Split long messages into chunks."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    lines = text.split("\n")
    current = ""

    for line in lines:
        if len(current) + len(line) + 1 <= max_len:
            current += line + "\n"
        else:
            if current:
                chunks.append(current.rstrip())
            # Handle very long single line
            while len(line) > max_len:
                chunks.append(line[:max_len])
                line = line[max_len:]
            current = line + "\n"

    if current:
        chunks.append(current.rstrip())

    return chunks


# ═══════════════════════════════════════════════
#  Send via Telegram
# ═══════════════════════════════════════════════

def send_telegram(text: str, token: str, chat_id: str) -> dict:
    """Send a single message via Telegram API."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()

    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def send_report(
    category: str,
    title: str,
    content: str,
    *,
    silent: bool = False,
) -> bool:
    """Send a complete report to Telegram.

    - Splits long messages
    - Logs to database
    - Queues on failure
    """
    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        # تم تعطيل الإشعار (لا يوجد token)
        return False

    header = build_header(category, title)
    full_message = header + content

    # Log in DB
    report_id = log_report(category, title, full_message)

    # Split and send
    chunks = split_message(full_message)
    total = len(chunks)
    success = True

    for i, chunk in enumerate(chunks, 1):
        if total > 1:
            chunk = f"<i>[{i}/{total}]</i>\n" + chunk

        result = send_telegram(chunk, token, chat_id)

        if result.get("ok"):
            print(f"✅ Chunk {i}/{total} sent")
        else:
            print(f"❌ Chunk {i}/{total} failed: {result}", file=sys.stderr)
            success = False

        time.sleep(0.5)  # Avoid rate limit

    # Update DB
    mark_sent(report_id, None if success else "chunk_failed")

    if not success:
        # Save to failed queue
        failed_file = FAILED_DIR / f"{report_id}.json"
        failed_file.write_text(json.dumps({
            "id": report_id,
            "category": category,
            "title": title,
            "content": full_message,
            "created_at": datetime.now().isoformat(),
        }, ensure_ascii=False, indent=2))

    return success


# ═══════════════════════════════════════════════
#  Templates
# ═══════════════════════════════════════════════

def report_task_complete(
    task_name: str,
    status: str,
    files: list,
    duration: str,
    notes: str = "",
) -> bool:
    """Report task completion."""
    content = f"""<b>المهمة:</b> {escape(task_name)}
<b>الحالة:</b> {escape(status)}
<b>المدة:</b> {escape(duration)}

<b>📁 الملفات ({len(files)}):</b>
"""
    for f in files[:20]:
        content += f"  • <code>{escape(f)}</code>\n"

    if len(files) > 20:
        content += f"  ... و {len(files) - 20} ملف آخر\n"

    if notes:
        content += f"\n<b>📝 ملاحظات:</b>\n{escape(notes)}"

    return send_report("task", f"إتمام: {task_name}", content)


def report_progress(
    project: str,
    percent: int,
    current: str,
    remaining: str,
) -> bool:
    """Report progress."""
    content = f"""<b>المشروع:</b> {escape(project)}
<b>التقدم:</b> {percent}%

<b>✅ الحالي:</b>
{escape(current)}

<b>⏳ المتبقي:</b>
{escape(remaining)}
"""
    return send_report("progress", "تحديث التقدم", content)


def report_alert(
    severity: str,
    message: str,
    details: str = "",
) -> bool:
    """Send critical alert."""
    icons = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
    icon = icons.get(severity.lower(), "⚠️")

    content = f"{icon} <b>خطورة:</b> {escape(severity.upper())}\n\n{escape(message)}"
    if details:
        content += f"\n\n<b>📋 تفاصيل:</b>\n{escape(details)}"

    return send_report("alert", f"تنبيه: {message[:50]}", content)


def report_state(
    state: dict,
) -> bool:
    """Send full state snapshot."""
    lines = []
    for key, value in state.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, indent=2)
        lines.append(f"<b>{escape(key)}:</b> {escape(value)}")

    content = "\n".join(lines)
    return send_report("state", "لقطة حالة النظام", content)


# ═══════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════

def main() -> None:
    """CLI entry point."""
    init_db()

    if len(sys.argv) < 2:
        print("Usage: vixona_report.py <command> [args]")
        print("Commands:")
        print("  test              — Send test message")
        print("  task <name>       — Report task completion")
        print("  progress          — Report progress")
        print("  state             — Send full state")
        print("  retry             — Retry failed reports")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "test":
        send_report("info", "اختبار Vixona", "✅ البوت يعمل بشكل صحيح")

    elif cmd == "task":
        name = sys.argv[2] if len(sys.argv) > 2 else "مهمة بدون اسم"
        report_task_complete(
            task_name=name,
            status="مكتمل",
            files=["src/example.py"],
            duration="0s",
            notes="من CLI",
        )

    elif cmd == "state":
        state = {
            "date": datetime.now().isoformat(),
            "host": os.uname().nodename,
            "cwd": os.getcwd(),
        }
        report_state(state)

    elif cmd == "retry":
        # Retry failed reports
        for f in FAILED_DIR.glob("*.json"):
            data = json.loads(f.read_text())
            ok = send_report(data["category"], data["title"], data["content"])
            if ok:
                f.unlink()
                print(f"✅ Retried: {f.name}")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
