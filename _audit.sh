#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  فحص شامل لنظام NovaMind
# ═══════════════════════════════════════════════════════════

R="/public"
SEP="━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "🔍 تقرير الفحص الشامل"
echo "$SEP"

# ─── 1. البيئة ───
echo ""
echo "📍 1. البيئة"
echo "$SEP"
echo "  النظام: $(cat /etc/os-release 2>/dev/null | grep PRETTY | cut -d= -f2)"
echo "  Python: $(python3 --version 2>&1)"
echo "  Git: $(git --version 2>&1)"
echo "  الحالة الحالية: $(pwd)"
echo "  HOME: $HOME"
echo "  REPO: $R"

# ─── 2. Git & SSH ───
echo ""
echo "📍 2. Git & SSH"
echo "$SEP"
cd "$R" 2>/dev/null
echo "  Branch: $(git branch --show-current 2>/dev/null)"
echo "  Remote: $(git remote get-url origin 2>/dev/null)"
echo "  آخر commit: $(git log -1 --oneline 2>/dev/null)"
echo "  حالة git config:"
git config --global --list 2>/dev/null | sed 's/^/    /'

if ssh -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
    echo "  ✅ SSH يعمل"
else
    echo "  ❌ SSH لا يعمل"
fi

# ─── 3. البوت ───
echo ""
echo "📍 3. البوت"
echo "$SEP"
echo "  ملف البوت: $(ls -la $R/hive/interface/unified_bot.py 2>/dev/null | awk '{print $5, $9}')"
echo "  عدد الأسطر: $(wc -l < $R/hive/interface/unified_bot.py 2>/dev/null)"

# فحص العملية
BOT_PID=$(pgrep -f "python3.*unified_bot.py" 2>/dev/null | head -1)
if [ -n "$BOT_PID" ]; then
    echo "  ✅ البوت يعمل (PID: $BOT_PID)"
    echo "  Uptime: $(ps -o etime= -p $BOT_PID 2>/dev/null | tr -d ' ')"
else
    echo "  ❌ البوت لا يعمل"
fi

# supervisor
if command -v supervisorctl >/dev/null 2>&1; then
    SUP=$(supervisorctl status novamind-bot 2>/dev/null)
    echo "  supervisord: $SUP"
fi

# ─── 4. الوكلاء ───
echo ""
echo "📍 4. الوكلاء"
echo "$SEP"
echo "  عدد الوكلاء: $(find $R/agent -name "*.py" 2>/dev/null | grep -v __pycache__ | wc -l)"
echo "  الملفات في agent/:"
find "$R/agent" -name "*.py" 2>/dev/null | grep -v __pycache__ | sed 's|/public/||;s/^/    /' | head -30

# ─── 5. أدوات Git/Agents الجديدة ───
echo ""
echo "📍 5. أدوات التحكم (git_control + agents_runner)"
echo "$SEP"
for f in "git_control.py" "agents_runner.py" "setup_env.sh" "start_bot.sh" "stop_bot.sh" "status_bot.sh"; do
    if [ -f "$R/$f" ]; then
        size=$(stat -c%s "$R/$f" 2>/dev/null || stat -f%z "$R/$f" 2>/dev/null)
        echo "  ✅ $f ($size bytes)"
    elif [ -f "$R/hive/interface/$f" ]; then
        size=$(stat -c%s "$R/hive/interface/$f" 2>/dev/null || stat -f%z "$R/hive/interface/$f" 2>/dev/null)
        echo "  ✅ hive/interface/$f ($size bytes)"
    else
        echo "  ❌ $f (مفقود)"
    fi
done

# ─── 6. أوامر Git/Agents في البوت ───
echo ""
echo "📍 6. أوامر Git/Agents المسجلة في البوت"
echo "$SEP"
GIT_CMDS=$(grep -c 'CommandHandler("git"\|CommandHandler("agents_' "$R/hive/interface/unified_bot.py" 2>/dev/null)
echo "  عدد الأوامر المسجلة: $GIT_CMDS"
grep -n 'CommandHandler("git"\|CommandHandler("agents_' "$R/hive/interface/unified_bot.py" 2>/dev/null | sed 's/^/    /'

# ─── 7. .env ───
echo ""
echo "📍 7. متغيرات البيئة (.env)"
echo "$SEP"
if [ -f "$R/.env" ]; then
    echo "  حجم: $(stat -c%s $R/.env 2>/dev/null || stat -f%z $R/.env 2>/dev/null) bytes"
    echo "  المتغيرات الرئيسية:"
    grep -E "^(GITHUB_TOKEN|TELEGRAM_BOT_TOKEN|TELEGRAM_ADMIN_ID|OPENROUTER_API_KEY_1|ZAI_API_KEY_1|GEMINI_API_KEY|NOVAMIND_MODEL)=" "$R/.env" 2>/dev/null | sed 's/=.*/=***/' | sed 's/^/    /'
else
    echo "  ❌ لا يوجد .env"
fi

# ─── 8. LLM APIs ───
echo ""
echo "📍 8. اختبار LLM APIs"
echo "$SEP"
set -a; source "$R/.env" 2>/dev/null; set +a

# OpenRouter
if [ -n "$OPENROUTER_API_KEY_1" ]; then
    HTTP=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $OPENROUTER_API_KEY_1" https://openrouter.ai/api/v1/auth/key 2>/dev/null)
    if [ "$HTTP" = "200" ]; then
        echo "  ✅ OpenRouter يعمل (key 1)"
    else
        echo "  ⚠️ OpenRouter: HTTP $HTTP"
    fi
else
    echo "  ❌ OpenRouter: لا يوجد key"
fi

# ZAI (تحقق فقط من وجود المفتاح)
if [ -n "$ZAI_API_KEY_1" ]; then
    echo "  ✅ ZAI: يوجد key 1 (الطول: ${#ZAI_API_KEY_1})"
fi

# Gemini
if [ -n "$GEMINI_API_KEY" ]; then
    echo "  ✅ Gemini: يوجد key (الطول: ${#GEMINI_API_KEY})"
fi

# GitHub
if [ -n "$GITHUB_TOKEN" ]; then
    HTTP=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user 2>/dev/null)
    if [ "$HTTP" = "200" ]; then
        echo "  ✅ GitHub Token يعمل"
    else
        echo "  ⚠️ GitHub Token: HTTP $HTTP"
    fi
fi

# ─── 9. الاختبارات ───
echo ""
echo "📍 9. الاختبارات (Tests)"
echo "$SEP"
if [ -d "$R/tests" ]; then
    echo "  عدد ملفات الاختبار: $(find $R/tests -name "test_*.py" 2>/dev/null | wc -l)"
    echo "  الملفات:"
    find "$R/tests" -name "test_*.py" 2>/dev/null | sed "s|$R/||;s/^/    /"
else
    echo "  ❌ لا يوجد مجلد tests"
fi

# ─── 10. المشاريع/المكونات الرئيسية ───
echo ""
echo "📍 10. المكونات الرئيسية"
echo "$SEP"
for dir in hive core agent tests scripts; do
    if [ -d "$R/$dir" ]; then
        count=$(find "$R/$dir" -name "*.py" 2>/dev/null | grep -v __pycache__ | wc -l)
        echo "  $dir/: $count ملف Python"
    fi
done

# ─── 11. Logs ───
echo ""
echo "📍 11. Logs"
echo "$SEP"
for log in /var/log/novamind-bot.log /tmp/novamind-bot.log; do
    if [ -f "$log" ]; then
        size=$(stat -c%s "$log" 2>/dev/null || stat -f%z "$log" 2>/dev/null)
        echo "  $log ($size bytes)"
        echo "  آخر 3 أسطر:"
        tail -3 "$log" 2>/dev/null | sed 's/^/    /'
    fi
done

# ─── 12. Git Status ───
echo ""
echo "📍 12. حالة Git الحالية"
echo "$SEP"
cd "$R" 2>/dev/null
git status -sb 2>/dev/null | head -20 | sed 's/^/  /'

echo ""
echo "$SEP"
echo "✅ انتهى الفحص"
