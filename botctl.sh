#!/bin/sh
PIDFILE="/tmp/novamind_bot.pid"
LOG="/tmp/novamind_bot.log"

case "$1" in
  start)
    pkill -9 -f novamind_bot 2>/dev/null
    sleep 2
    cd /public
    nohup python3 agent/novamind_bot.py > "$LOG" 2>&1 &
    echo $! > "$PIDFILE"
    echo "Started: $(cat $PIDFILE)"
    sleep 5
    tail -5 "$LOG"
    ;;
  stop)
    pkill -9 -f novamind_bot 2>/dev/null
    rm -f "$PIDFILE"
    echo "Stopped"
    ;;
  status)
    ps aux | grep novamind_bot | grep -v grep || echo "Not running"
    ;;
  logs)
    tail -20 "$LOG"
    ;;
  *)
    echo "Usage: $0 {start|stop|status|logs}"
    ;;
esac
