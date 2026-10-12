#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  إيقاف البوت
# ═══════════════════════════════════════════════════════════

echo "🛑 إيقاف البوت..."

if supervisorctl status novamind-bot 2>/dev/null | grep -q "RUNNING"; then
    supervisorctl stop novamind-bot >/dev/null 2>&1
    echo "  ✅ تم الإيقاف عبر supervisord"
else
    echo "  ℹ️ البوت لا يعمل"
fi

# إيقاف أي عملية متبقية
PIDS=$(pgrep -f "python3.*unified_bot.py" 2>/dev/null)
if [ -n "$PIDS" ]; then
    echo "$PIDS" | xargs -r kill 2>/dev/null
    sleep 1
    echo "  ✅ تم إيقاف عمليات متبقية: $PIDS"
fi
