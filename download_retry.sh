#!/bin/sh
# Auto-retry download with wget

URL="https://huggingface.co/continuum-ai/qwen3.5-4b-code-forged-GGUF/resolve/main/qwen3.5-4b-code-forged-Q4_K_M.gguf"
FILE="/public/qwen-coder.gguf"
LOG="/public/wget.log"
MAX_RETRIES=50

cd /public

for i in $(seq 1 $MAX_RETRIES); do
    echo "[$(date '+%H:%M:%S')] Attempt #$i" >> "$LOG"
    
    # Check if already complete
    if [ -f "$FILE" ]; then
        SIZE=$(stat -c%s "$FILE" 2>/dev/null || echo 0)
        if [ "$SIZE" -gt 2700000000 ]; then
            echo "[$(date '+%H:%M:%S')] Download complete: $SIZE bytes" >> "$LOG"
            exit 0
        fi
    fi
    
    # Try download with resume
    wget -c --tries=10 --timeout=60 --waitretry=10 \
        -O "$FILE" "$URL" >> "$LOG" 2>&1
    
    RET=$?
    
    if [ $RET -eq 0 ]; then
        echo "[$(date '+%H:%M:%S')] wget succeeded" >> "$LOG"
        exit 0
    fi
    
    echo "[$(date '+%H:%M:%S')] wget failed with code $RET, retrying in 10s..." >> "$LOG"
    sleep 10
done

echo "[$(date '+%H:%M:%S')] Max retries reached" >> "$LOG"
