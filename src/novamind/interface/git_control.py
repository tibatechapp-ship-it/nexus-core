"""
git_control.py — وحدة التحكم بـ Git للبوت
تستخدم SSH (المفعّل) + GITHUB_TOKEN (من .env) للعمليات
"""
from __future__ import annotations
import subprocess
import os
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_PATH = "/public"
BACKUP_DIR = "/tmp/git_backups"
GITHUB_REPO = "git@github.com:tibatechapp-ship-it/novamind-core.git"


def _run(args, timeout=120, cwd=REPO_PATH):
    """تشغيل أمر وإرجاع (نجاح، مخرجات)"""
    try:
        env = os.environ.copy()
        env["GIT_SSH_COMMAND"] = "ssh -o StrictHostKeyChecking=no -o BatchMode=yes"
        result = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True,
            timeout=timeout, env=env,
        )
        out = (result.stdout + result.stderr).strip()
        return result.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, "⏰ انتهت المهلة"
    except Exception as e:
        return False, f"❌ {e}"


# ═══════════════════════════════════════════════════════
#  أوامر Git الأساسية
# ═══════════════════════════════════════════════════════

def git_status():
    """حالة المستودع"""
    ok, out = _run(["git", "status", "-sb"])
    if not ok:
        return f"❌ {out}"
    lines = out.split("\n")
    branch = lines[0] if lines else "?"
    changes = [l for l in lines[1:] if l.strip()]
    result = f"🌿 *{branch}*\n"
    if changes:
        result += f"📝 تغييرات: {len(changes)} ملف\n"
        for c in changes[:10]:
            result += f"  `{c}`\n"
        if len(changes) > 10:
            result += f"  ... و {len(changes) - 10} آخر\n"
    else:
        result += "✅ نظيف (لا تغييرات)\n"
    return result


def git_log(n=5):
    """آخر n commits"""
    ok, out = _run(["git", "log", f"-{n}", "--oneline", "--decorate"])
    if not ok:
        return f"❌ {out}"
    return "📜 *آخر commits:*\n" + "\n".join(f"  `{l}`" for l in out.split("\n"))


def git_pull():
    """سحب التحديثات"""
    ok, out = _run(["git", "pull", "--rebase"])
    if not ok:
        return f"❌ فشل السحب:\n`{out[:400]}`"
    return f"✅ *تم السحب*\n`{out[:400]}`"


def git_commit(message):
    """إنشاء commit مع إضافة كل التغييرات"""
    if not message or not message.strip():
        return "❌ يجب إعطاء رسالة commit"
    _run(["git", "add", "-A"])
    ok, out = _run(["git", "commit", "-m", message])
    if not ok:
        if "nothing to commit" in out.lower():
            return "ℹ️ لا توجد تغييرات للـ commit"
        return f"❌ فشل commit:\n`{out[:400]}`"
    # استخراج hash
    _, hash_out = _run(["git", "rev-parse", "--short", "HEAD"])
    return f"✅ *تم commit* `{hash_out}`\n📝 {message}"


def git_push():
    """دفع التغييرات"""
    ok, out = _run(["git", "push"])
    if not ok:
        return f"❌ فشل الدفع:\n`{out[:400]}`"
    return f"✅ *تم الدفع*\n`{out[:300]}`"


def git_sync(message=None):
    """commit + push في خطوة واحدة"""
    msg = message or f"auto(agent): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    r1 = git_commit(msg)
    if "❌" in r1:
        return r1
    if "ℹ️" in r1:
        return r1  # لا شيء لدفعه
    r2 = git_push()
    return f"{r1}\n{r2}"


def git_backup():
    """نسخة احتياطية كاملة (mirror)"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    name = f"backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.git"
    path = os.path.join(BACKUP_DIR, name)
    ok, out = _run(
        ["git", "clone", "--mirror", GITHUB_REPO, path],
        timeout=600, cwd=BACKUP_DIR,
    )
    if not ok:
        return f"❌ فشل النسخ الاحتياطي:\n`{out[:400]}`"
    # الحجم
    _, size = _run(["du", "-sh", path], cwd=BACKUP_DIR)
    return f"✅ *نسخة احتياطية*\n📦 `{name}`\n💾 {size}"


def git_branches():
    """عرض الفروع"""
    ok, out = _run(["git", "branch", "-a"])
    if not ok:
        return f"❌ {out}"
    return "🌿 *الفروع:*\n" + "\n".join(f"  `{l.strip()}`" for l in out.split("\n") if l.strip())


def git_diff_stat():
    """إحصائيات التغييرات"""
    ok, out = _run(["git", "diff", "--stat", "HEAD"])
    if not ok or not out:
        return "✅ لا توجد تغييرات"
    return f"📊 *التغييرات:*\n`{out[:600]}`"


# ═══════════════════════════════════════════════════════
#  اختبار سريع عند التشغيل المباشر
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    print(git_status())
    print()
    print(git_log(3))
