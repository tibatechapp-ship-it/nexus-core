#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  سكربت الإعداد الموحد لبيئة NovaMind
#  شغّله في بداية كل جلسة: source /public/setup_env.sh
# ═══════════════════════════════════════════════════════════

echo "🚀 بدء إعداد البيئة..."

# ─── 1. المسارات ───
export REPO="/public"
cd "$REPO" || { echo "❌ /public غير موجود"; return 1; }

# ─── 2. SSH Agent ───
if [ -z "$SSH_AUTH_SOCK" ] || ! ssh-add -l >/dev/null 2>&1; then
    eval "$(ssh-agent -s)" > /dev/null 2>&1
    if [ -f ~/.ssh/id_ed25519 ]; then
        ssh-add ~/.ssh/id_ed25519 > /dev/null 2>&1
        echo "  ✅ SSH agent جاهز"
    fi
else
    echo "  ✅ SSH agent يعمل مسبقاً"
fi

# ─── 3. اختبار SSH ───
if ssh -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
    echo "  ✅ SSH مع GitHub يعمل"
else
    echo "  ⚠️ SSH مع GitHub لا يعمل (تحقق من المفتاح)"
fi

# ─── 4. Git config ───
if [ -f /public/.gitconfig ]; then
    export GIT_CONFIG_GLOBAL="/public/.gitconfig"
    echo "  ✅ Git config دائم: /public/.gitconfig"
fi

# ─── 5. Python path ───
export PYTHONPATH="$REPO:$PYTHONPATH"
echo "  ✅ PYTHONPATH جاهز"

# ─── 6. اختصار مفيد ───
alias gs="git status -sb"
alias gl="git log --oneline -10"
alias gp="git pull --rebase"
alias gb="/public/hive/interface/git_control.py"
echo "  ✅ اختصارات: gs, gl, gp"

echo "✅ البيئة جاهزة"

# ─── 7. تحميل .env ───
if [ -f /public/.env ]; then
    set -a
    source /public/.env
    set +a
    echo "  ✅ .env محمّل (GITHUB_TOKEN: ${#GITHUB_TOKEN} حرف)"
fi
