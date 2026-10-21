#!/bin/sh
# NovaMind v2.1.0 — Watchdog
# يراقب الخدمات ويشغّلها إن توقفت

LOG="/tmp/nm_watchdog.log"
echo "[$(date)] Watchdog v2.1 started" >> "$LOG"

while true; do
    # Redis
    if ! pgrep -f "redis-server" > /dev/null; then
        echo "[$(date)] Redis stopped → restart" >> "$LOG"
        mkdir -p /tmp/nm_redis
        redis-server --port 6379 --dir /tmp/nm_redis --daemonize yes --maxmemory 256mb 2>&1
    fi
    
    # Ollama
    if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "[$(date)] Ollama stopped → restart" >> "$LOG"
        nohup ollama serve > /tmp/nm_ollama.log 2>&1 &
    fi
    
    # NovaMind Bot (النسخة الجديدة فقط)
    if ! pgrep -f "novamind.py bot" > /dev/null; then
        echo "[$(date)] NovaMind bot stopped → restart" >> "$LOG"
        cd /public
        nohup python3 novamind.py bot > /tmp/nm_bot.log 2>&1 &
    fi
    
    sleep 30
done
