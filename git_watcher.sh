#!/bin/sh
LOG="/var/log/novamind/git_watcher.log"
mkdir -p /var/log/novamind
cd /public
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"; }
log "Git Watcher started"
ITER=0
while true; do
    ITER=$((ITER + 1))
    CHANGED=$(git status --porcelain | wc -l)
    if [ "$CHANGED" -gt 0 ]; then
        git add -A 2>/dev/null
        git commit -m "chore(watcher): autosave $(date '+%H:%M:%S')" 2>/dev/null
        log "committed $CHANGED"
    fi
    AHEAD=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo 0)
    [ "$AHEAD" -gt 0 ] && git push 2>/dev/null && log "pushed $AHEAD"
    BEHIND=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)
    [ "$BEHIND" -gt 0 ] && git pull --rebase 2>/dev/null && log "pulled $BEHIND"
    [ $((ITER % 5)) -eq 0 ] && log "[#$ITER] c=$CHANGED a=$AHEAD b=$BEHIND"
    sleep 60
done
