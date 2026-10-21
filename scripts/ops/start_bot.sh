#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  تشغيل البوت بشكل ذكي
# ═══════════════════════════════════════════════════════════

echo "🤖 تشغيل البوت..."

# ─── 1. فحص: هل supervisord يديره؟ ───
if supervisorctl status novamind-bot 2>/dev/null | grep -q "RUNNING"; then
    PID=$(supervisorctl status novamind-bot | grep -oE "pid [0-9]+" | awk '{print $2}')
    echo "  ✅ البوت يعمل عبر supervisord (PID: $PID)"
    return 0 2>/dev/null || exit 0
fi

# ─── 2. فحص: هل supervisord يعمل أصلاً؟ ───
if ! pgrep -f "supervisord" >/dev/null 2>&1; then
    echo "  ⚙️ تشغيل supervisord..."
    supervisord -c /etc/supervisor/supervisord.conf >/dev/null 2>&1
    sleep 3
fi

# ─── 3. بدء البوت عبر supervisord ───
supervisorctl start novamind-bot >/dev/null 2>&1
sleep 3

if supervisorctl status novamind-bot 2>/dev/null | grep -q "RUNNING"; then
    PID=$(supervisorctl status novamind-bot | grep -oE "pid [0-9]+" | awk '{print $2}')
    echo "  ✅ البوت يعمل (PID: $PID)"
else
    echo "  ❌ فشل التشغيل"
    tail -10 /var/log/novamind-bot.log 2>/dev/null
fi
