#!/bin/sh
# NovaMind Keep-Alive
# يراقب البوت كل 60 ثانية ويشغّله إن توقف

LOG="/var/log/novamind-keepalive.log"
BOT="/public/hive/interface/unified_bot.py"
PID_FILE="/tmp/novamind.pid"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"
}

log "=== Keep-Alive started ==="

while true; do
    # فحص supervisord
    if ! pgrep -f supervisord > /dev/null 2>&1; then
        log "supervisord stopped → restart"
        rm -f /run/supervisord.sock /run/supervisord.pid
        supervisord -c /etc/supervisor/supervisord.conf >/dev/null 2>&1
        sleep 5
    fi

    # فحص البوت
    if ! pgrep -f "unified_bot.py" > /dev/null 2>&1; then
        log "unified_bot stopped → restart via supervisor"
        supervisorctl start novamind-bot >/dev/null 2>&1
        sleep 5
    fi

    # كل 60 ثانية
    sleep 60
done
