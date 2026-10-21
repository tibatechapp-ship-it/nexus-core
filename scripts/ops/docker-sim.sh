#!/bin/sh
echo "═══════════════════════════════════════════"
echo "  NovaMind — Process Manager (Docker Sim)"
echo "═══════════════════════════════════════════"

start_redis() {
    if pgrep -f "redis-server" > /dev/null; then
        echo "✅ Redis:   already running"
        return
    fi
    if ! command -v redis-server > /dev/null 2>&1; then
        echo "⚠️  Redis not installed — installing..."
        apk add redis 2>&1 | tail -2
    fi
    mkdir -p /tmp/nm_redis
    redis-server --port 6379 --dir /tmp/nm_redis --daemonize yes --maxmemory 512mb 2>/dev/null
    sleep 1
    pgrep -f "redis-server" > /dev/null && echo "✅ Redis:   started" || echo "❌ Redis:   failed"
}

start_ollama() {
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "✅ Ollama:  already running"
        return
    fi
    nohup ollama serve > /tmp/nm_ollama.log 2>&1 &
    sleep 4
    curl -s http://localhost:11434/api/tags > /dev/null 2>&1 && echo "✅ Ollama:  started" || echo "❌ Ollama:  failed"
}

start_bot() {
    pkill -9 -f "novamind_bot" 2>/dev/null
    sleep 1
    cd /public
    nohup python3 agent/novamind_bot.py > /tmp/nm_bot.log 2>&1 &
    BOT_PID=$!
    echo $BOT_PID > /tmp/nm_bot.pid
    sleep 4
    ps -p $BOT_PID > /dev/null 2>&1 && echo "✅ Bot:     started (PID $BOT_PID)" || echo "❌ Bot:     failed"
}

stop_all() {
    pkill -9 -f "novamind_bot" 2>/dev/null && echo "🛑 Bot stopped"
    pkill -9 -f "redis-server" 2>/dev/null && echo "🛑 Redis stopped"
    echo "✅ Ollama:  kept running (shared)"
}

status() {
    echo "═══════════════════════════════════════════"
    echo "  NovaMind Services Status"
    echo "═══════════════════════════════════════════"

    if pgrep -f "redis-server" > /dev/null; then
        echo "✅ Redis:   running (PID $(pgrep -f redis-server | head -1))"
    else
        echo "❌ Redis:   stopped"
    fi

    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        MODELS=$(curl -s http://localhost:11434/api/tags | grep -o '"name":"[^"]*"' | wc -l)
        echo "✅ Ollama:  running ($MODELS models)"
    else
        echo "❌ Ollama:  stopped"
    fi

    if pgrep -f "novamind_bot" > /dev/null; then
        PID=$(pgrep -f novamind_bot | head -1)
        echo "✅ Bot:     running (PID $PID)"
    else
        echo "❌ Bot:     stopped"
    fi
    echo "═══════════════════════════════════════════"
}

case "$1" in
    start)
        echo "🚀 Starting NovaMind services..."
        echo ""
        start_redis
        start_ollama
        start_bot
        echo ""
        status
        ;;
    stop)    stop_all ;;
    restart) stop_all; sleep 2; "$0" start ;;
    status)  status ;;
    logs)    tail -30 /tmp/nm_bot.log 2>/dev/null ;;
    *)       echo "Usage: $0 {start|stop|restart|status|logs}" ;;
esac
