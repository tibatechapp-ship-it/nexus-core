#!/bin/bash
R="/public"
S="━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "🔍 فحص سريع"
echo "$S"

echo ""
echo "1. البيئة"
echo "  Python: $(python3 --version 2>&1)"
echo "  Git: $(git --version 2>&1)"
echo "  PWD: $(pwd)"
echo "  HOME: $HOME"

echo ""
echo "2. Git"
cd "$R"
echo "  Branch: $(git branch --show-current 2>/dev/null)"
echo "  Remote: $(git remote get-url origin 2>/dev/null)"
echo "  آخر commit: $(git log -1 --oneline 2>/dev/null)"

echo ""
echo "3. SSH"
ssh -T git@github.com 2>&1 | head -1

echo ""
echo "4. البوت"
PID=$(pgrep -f "unified_bot.py" | head -1)
if [ -n "$PID" ]; then
    echo "  ✅ يعمل (PID: $PID)"
else
    echo "  ❌ لا يعمل"
fi

echo ""
echo "5. الوكلاء"
COUNT=$(find "$R/agent" -name "*.py" 2>/dev/null | grep -v __pycache__ | wc -l)
echo "  عدد الملفات: $COUNT"

echo ""
echo "6. أدواتنا الجديدة"
for f in "hive/interface/git_control.py" "hive/interface/agents_runner.py"; do
    if [ -f "$R/$f" ]; then
        SIZE=$(wc -l < "$R/$f")
        echo "  ✅ $f ($SIZE سطر)"
    else
        echo "  ❌ $f"
    fi
done

echo ""
echo "7. أوامر Git/Agents في البوت"
grep -c 'CommandHandler("git"\|CommandHandler("agents_' "$R/hive/interface/unified_bot.py" 2>/dev/null | xargs echo "  عدد الأوامر:"

echo ""
echo "8. .env"
if [ -f "$R/.env" ]; then
    echo "  ✅ موجود ($(wc -l < $R/.env) سطر)"
    grep -E "^(GITHUB_TOKEN|TELEGRAM_ADMIN_ID|OPENROUTER_API_KEY_1)=" "$R/.env" 2>/dev/null | sed 's/=.*/=***/' | sed 's/^/    /'
fi

echo ""
echo "9. حالة Git"
cd "$R"
git status -sb 2>/dev/null | head -15

echo ""
echo "$S"
echo "✅ انتهى"
