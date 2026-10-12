#!/bin/sh
# ═══════════════════════════════════════════════════════════
#  HiveLoop-X Auto-Save Script
#  يحفظ التعديلات تلقائياً في Git كل X دقيقة
# ═══════════════════════════════════════════════════════════

set -e
cd /public

LOG="/var/log/novamind-autosave.log"

# ─── دوال مساعدة ───
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | $1" >> "$LOG"
}

# ─── 1. فحص هل فيه تعديلات؟ ───
if [ -z "$(git status --porcelain)" ]; then
    # مفيش تعديلات — ما نعملش commit
    exit 0
fi

log "تعديلات موجودة — بدء الحفظ"

# ─── 2. حماية: تجاهل .env وأي ملفات حساسة ───
# (مضمونة في .gitignore، بس نتأكد)
if git status --porcelain | grep -qE "^\?\?\s+\.env|^ M\s+\.env"; then
    log "⚠️  .env مكشوف في git status — تجاهل العملية"
    exit 1
fi

# ─── 3. أضف كل التعديلات ───
git add -- hive core/llm_router.py core/company tests docs .gitignore 2>/dev/null || true

# ─── 4. commit مع timestamp ───
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
CHANGED=$(git diff --cached --name-only | wc -l)

if [ "$CHANGED" -gt 0 ]; then
    git commit -m "chore(autosave): $TIMESTAMP ($CHANGED files)" 2>&1 | head -1 >> "$LOG"
    log "✅ commit ناجح — $CHANGED ملف"
else
    log "لا يوجد شيء للـ commit"
fi

# ─── 5. push (اختياري — بدون تكسير عند غياب الشبكة) ───
if git remote | grep -q origin; then
    if git push origin HEAD 2>/dev/null; then
        log "✅ push ناجح"
    else
        log "⚠️  push فشل (ربما لا اتصال) — سيبقى محلياً"
    fi
fi

log "━━━ انتهى ━━━"
