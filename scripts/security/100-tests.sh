#!/data/data/com.termux/files/usr/bin/bash
# 100-tests.sh — اختبارات أمنية دفاعية

set -uo pipefail

PROJECT="$HOME/nexus-core"
REPORT_DIR="$PROJECT/reports/security"
mkdir -p "$REPORT_DIR"

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
REPORT="$REPORT_DIR/security-tests-$TIMESTAMP.md"

G='\033[0;32m'; C='\033[0;36m'; B='\033[1m'; Y='\033[1;33m'; N='\033[0m'
log() { echo -e "${G}[$(date +%H:%M:%S)]${N} $*"; }
title() { echo -e "${C}${B}$*${N}"; }
line() { echo -e "${C}═══════════════════════════════════════════${N}"; }

{
    echo "# 🛡️ اختبارات أمنية دفاعية — Nexus-Core"
    echo ""
    echo "**التاريخ:** $(date)"
    echo ""
    echo "---"
    echo ""
} > "$REPORT"

TESTS=(
    "ما أفضل ممارسات حماية GitHub Secrets؟"
    "كيف نمنع تسريب المفاتيح في Git History؟"
    "كيف نحمي GitHub Actions من الحقن؟"
    "ما أفضل سياسات Branch Protection؟"
    "كيف نحصن AI Agents من Prompt Injection؟"
    "كيف نمنع Jailbreak Attacks؟"
    "كيف نحمي System Prompts؟"
    "ما أفضل ممارسات Context Isolation؟"
    "كيف نحمي API من Unauthorized Access؟"
    "ما أفضل ممارسات API Authentication؟"
    "كيف نستخدم JWT بشكل آمن؟"
    "كيف نمنع API Key Leakage؟"
    "كيف نحصن Council من Prompt Injection؟"
    "كيف نحمي Council من Role Hijacking؟"
    "كيف نمنع Genome Manipulation؟"
    "كيف نمنع pickle Deserialization Attacks؟"
)

TOTAL=${#TESTS[@]}
START_TIME=$(date +%s)
PASS=0
FAIL=0

line
title "  🛡️ اختبارات أمنية"
line
echo ""
log "📊 إجمالي: $TOTAL"
log "📄 التقرير: $REPORT"
echo ""

for i in "${!TESTS[@]}"; do
    TEST="${TESTS[$i]}"
    NUM=$((i+1))
    
    echo -e "${C}[$NUM/$TOTAL]${N} $TEST"
    
    echo "## [$NUM/$TOTAL] $TEST" >> "$REPORT"
    echo "" >> "$REPORT"
    
    RESPONSE=$(timeout 30 curl -N -s -X POST "http://127.0.0.1:8080/api/council/stream" \
        -H "Content-Type: application/json" \
        -d "{\"topic\": \"$TEST\", \"rounds\": 1}" 2>/dev/null | \
        grep "member_message" | head -2 | python3 -c "
import json, sys
for line in sys.stdin:
    try:
        d = json.loads(line.strip().replace('data: ', ''))
        if d.get('type') == 'member_message':
            print(f\"### {d.get('emoji', '')} {d.get('name', '?')}\")
            print()
            print(d.get('content', '')[:400])
            print()
    except: pass
" 2>/dev/null)
    
    if [ -n "$RESPONSE" ]; then
        echo "$RESPONSE" >> "$REPORT"
        PASS=$((PASS+1))
        echo -e "${G}  ✅${N}"
    else
        echo "⚠️ لا رد" >> "$REPORT"
        FAIL=$((FAIL+1))
        echo -e "${Y}  ⚠️${N}"
    fi
    
    echo "" >> "$REPORT"
    echo "---" >> "$REPORT"
    echo "" >> "$REPORT"
    
    [ "$NUM" -lt "$TOTAL" ] && sleep 6
done

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

line
title "  ✅ اكتملت"
line
log "✅ نجح: $PASS"
log "⚠️ فشل: $FAIL"
log "⏱️  المدة: $((DURATION/60))د $((DURATION%60))ث"
log "📄 التقرير: $REPORT"

{
    echo ""
    echo "---"
    echo ""
    echo "## 📊 الملخص"
    echo ""
    echo "- **إجمالي:** $TOTAL"
    echo "- **نجح:** $PASS"
    echo "- **فشل:** $FAIL"
    echo "- **المدة:** $((DURATION/60))د $((DURATION%60))ث"
} >> "$REPORT"
