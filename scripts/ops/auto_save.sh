#!/bin/sh
# NovaMind Auto-Save — كل 5 دقائق
# يحفظ التغييرات في git تلقائياً

LOG="/var/log/novamind-autosave.log"
cd /public

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"
}

log "=== Auto-Save started ==="

while true; do
    sleep 300  # 5 دقائق

    # هل هناك تغييرات؟
    if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
        log "Changes detected → saving"
        git add -A 2>/dev/null
        git commit -m "chore(autosave): $(date '+%Y-%m-%d %H:%M:%S')" 2>/dev/null
        git push 2>/dev/null
        log "Saved"
    fi
done
