#!/bin/sh
# NovaMind Manager — Enhanced Version
cd /public/agent/novamind

PID_FILE=".nova/novamind.pid"
LOG_FILE=".nova/logs/24_7.log"
SCRIPT="run_novamind_complete.py"

case "$1" in
    start)
        pkill -f "$SCRIPT" 2>/dev/null
        sleep 1
        nohup python3 "$SCRIPT" > "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
        sleep 2
        if ps -p $(cat "$PID_FILE") > /dev/null 2>&1; then
            echo "✅ بدأ بنجاح (PID: $(cat $PID_FILE))"
        else
            echo "❌ فشل التشغيل"
            tail -20 "$LOG_FILE"
        fi
        ;;
    stop)
        if [ -f "$PID_FILE" ]; then
            kill $(cat "$PID_FILE") 2>/dev/null
            sleep 1
            rm -f "$PID_FILE"
            echo "🛑 توقف"
        else
            pkill -f "$SCRIPT" 2>/dev/null
            echo "🛑 توقف (بالاسم)"
        fi
        ;;
    status)
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            if ps -p $PID > /dev/null 2>&1; then
                echo "✅ يعمل (PID: $PID)"
                echo ""
                echo "آخر 5 أسطر من السجل:"
                tail -5 "$LOG_FILE" 2>/dev/null
            else
                echo "⚠️  PID موجود لكن العملية متوقفة"
            fi
        else
            if pgrep -f "$SCRIPT" > /dev/null; then
                echo "✅ يعمل (بدون PID file)"
            else
                echo "❌ لا يعمل"
            fi
        fi
        ;;
    restart)
        "$0" stop
        sleep 2
        "$0" start
        ;;
    report)
        python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, '/public/agent/novamind')
from dotenv import load_dotenv
load_dotenv('/public/agent/novamind/.env')
from core.automation.daily_reporter import DailyReporter
r = DailyReporter(Path('/public/agent/novamind'))
if r.send_daily():
    print('✅ تقرير مرسل')
else:
    print('❌ فشل')
"
        ;;
    logs)
        tail -f "$LOG_FILE"
        ;;
    *)
        echo "NovaMind Manager"
        echo ""
        echo "الاستخدام:"
        echo "  ./nova.sh start     — تشغيل"
        echo "  ./nova.sh stop      — إيقاف"
        echo "  ./nova.sh restart   — إعادة تشغيل"
        echo "  ./nova.sh status    — حالة"
        echo "  ./nova.sh report    — تقرير فوري"
        echo "  ./nova.sh logs      — متابعة السجل"
        ;;
esac
