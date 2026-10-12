#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  حالة البوت
# ═══════════════════════════════════════════════════════════

echo "📊 حالة البوت"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━"

# supervisord
if supervisorctl status novamind-bot 2>/dev/null | grep -q "RUNNING"; then
    echo "✅ يعمل عبر supervisord"
    supervisorctl status novamind-bot | sed 's/^/   /'
    PID=$(supervisorctl status novamind-bot | grep -oE "pid [0-9]+" | awk '{print $2}')
    echo "   Uptime: $(ps -o etime= -p $PID 2>/dev/null | tr -d ' ')"
else
    echo "❌ لا يعمل عبر supervisord"
fi

# عمليات python
PIDS=$(pgrep -f "python3.*unified_bot.py" 2>/dev/null)
if [ -n "$PIDS" ]; then
    echo "✅ عمليات Python: $PIDS"
else
    echo "❌ لا توجد عمليات Python"
fi

# آخر log
echo ""
echo "📄 آخر 5 أسطر:"
tail -5 /var/log/novamind-bot.log 2>/dev/null | sed 's/^/   /'

# حالة Telegram Conflict
if tail -50 /var/log/novamind-bot.log 2>/dev/null | grep -q "Conflict"; then
    echo ""
    echo "⚠️ تحذير: يوجد Conflict في Telegram (بوت آخر يستخدم نفس التوكن)"
fi
