#!/bin/sh
# Security Watcher — يشغّل Security Scanner كل 10 دقائق
LOG="/var/log/novamind/security_watcher.log"
mkdir -p /var/log/novamind
cd /public

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"; }
log "Security Watcher started"

ITER=0
while true; do
    ITER=$((ITER + 1))

    # شغّل Security Scanner
    RESULT=$(timeout 60 python3 /public/hive_security_scanner.py 2>&1 | tail -1)
    EXIT=$?

    if [ $EXIT -eq 0 ]; then
        log "[#$ITER] ✅ Clean"
    else
        log "[#$ITER] ⚠️ Issues found (exit=$EXIT)"
        log "$RESULT"
    fi

    # كل 10 دقائق
    sleep 600
done
