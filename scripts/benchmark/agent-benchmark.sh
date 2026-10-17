#!/data/data/com.termux/files/usr/bin/bash
# agent-benchmark.sh — اختبار كفاءة الوكلاء على 16 معيار

set -uo pipefail

PROJECT="$HOME/nexus-core"
REPORT_DIR="$PROJECT/reports/benchmark"
mkdir -p "$REPORT_DIR"

# العنوان الأساسي للبوابة الموحّدة (runit service `nexus-core` على 8000 افتراضياً).
PORT="${NEXUS_PORT:-8000}"
BASE="http://127.0.0.1:$PORT"

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
REPORT="$REPORT_DIR/benchmark-$TIMESTAMP.md"
JSON_REPORT="$REPORT_DIR/benchmark-$TIMESTAMP.json"

G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; C='\033[0;36m'; B='\033[1m'; N='\033[0m'

log() { echo -e "${G}[$(date +%H:%M:%S)]${N} $*"; }
title() { echo -e "${C}${B}$*${N}"; }
line() { echo -e "${C}═══════════════════════════════════════════${N}"; }

# ═══ 16 معيار (من جدول Z.ai) ═══
declare -A BENCHMARKS=(
    ["TerminalBench"]="مهمة Terminal: نفّذ سلسلة أوامر لفحص نظام Linux، اذكر الأدوات، والنتائج المتوقعة"
    ["DeepSWE"]="مهمة برمجة عميقة: صمّم دالة Python لحل مشكلة تعقيد خوارزمي O(n log n)"
    ["NL2Repo"]="حوّل هذا الوصف إلى كود: تطبيق ويب بسيط بـ FastAPI مع GET /health"
    ["ProgramBench"]="حل مشكلة برمجية: اكتب دالة للتحقق من palindrome مع مراعاة Unicode"
    ["FrontierSWE"]="مهمة متقدمة: اقترح معمارية Microservices لتطبيق يحتمل 1M مستخدم"
    ["SWEMarathon"]="مهمة طويلة: صمّم نظام أمان متعدد الطبقات لتطبيق مالي"
    ["PostTrainBench"]="قيّم: كيف يحسّن Fine-tuning أداء النموذج على مهام محددة؟"
    ["CyberGym"]="تحليل دفاعي: ما أفضل ممارسات أمان WebSocket في تطبيق chat؟"
    ["ExploitGym"]="تحليل دفاعي: ما أخطر 3 ثغرات في REST APIs وكيف نمنعها؟"
    ["ExploitBench"]="تحليل دفاعي: ما ثغرات Prompt Injection في AI Agents؟"
    ["Toolathlon"]="مهمة أدوات: كيف تستخدم Git + Docker + pytest لحل مشكلة CI/CD؟"
    ["AutomationBench"]="أتمتة: صمّم workflow لأتمتة نسخ احتياطي يومي مع إشعارات"
    ["ALECLI"]="وكيل CLI: كيف تبني وكيلاً يقرأ ملفات ويعالجها ويولّد تقارير؟"
    ["HLEWithTools"]="استدلال مع أدوات: حلّل مشكلة أداء تطبيق باستخدام Profiler"
    ["GDPvalAA"]="مهمة واقعية: قيّم مشروع SaaS من حيث الجدوى والتكلفة والمخاطر"
    ["ToolUseAdvanced"]="أدوات متقدمة: صمّم نظام Multi-Agent يستخدم 10 أدوات مختلفة"
)

# ═══ عدد أعضاء المجلس (حقيقي من /api/status لا رقم مكتوب يدوياً) ═══
N_MEMBERS=$(curl -s -m 5 "${BASE}/api/status" 2>/dev/null | python3 -c \
    "import json,sys; print(json.load(sys.stdin).get('components',{}).get('council_members',0))" \
    2>/dev/null)
[ -n "$N_MEMBERS" ] || N_MEMBERS=0

# ═══ بدء التقرير ═══
{
    echo "# 🧪 تقرير اختبار كفاءة الوكلاء — Nexus-Core"
    echo ""
    echo "**التاريخ:** $(date)"
    echo "**المعايير:** ${#BENCHMARKS[@]}"
    echo "**الأعضاء:** $N_MEMBERS"
    echo "**إجمالي الاختبارات:** $((${#BENCHMARKS[@]} * N_MEMBERS))"
    echo ""
    echo "---"
    echo ""
} > "$REPORT"

# ═══ JSON للتحليل ═══
echo "{" > "$JSON_REPORT"
echo "  \"timestamp\": \"$TIMESTAMP\"," >> "$JSON_REPORT"
echo "  \"benchmarks\": [" >> "$JSON_REPORT"

line
title "  🧪 اختبار كفاءة الوكلاء"
line
echo ""
log "📊 المعايير: ${#BENCHMARKS[@]}"
log "👥 الأعضاء: $N_MEMBERS"
log "📄 التقرير: $REPORT"
echo ""

START_TIME=$(date +%s)
TOTAL=0
SUCCESS=0
FAIL=0

FIRST_BM=true
for BENCH in "${!BENCHMARKS[@]}"; do
    TASK="${BENCHMARKS[$BENCH]}"
    TOTAL=$((TOTAL+1))
    
    echo -e "${C}═══ [$TOTAL/${#BENCHMARKS[@]}] $BENCH ═══${N}"
    echo ""
    
    # سجل في التقرير
    {
        echo "## 🎯 [$TOTAL] $BENCH"
        echo ""
        echo "**المهمة:** $TASK"
        echo ""
    } >> "$REPORT"
    
    # استدعاء Council
    RESPONSE=$(timeout 60 curl -N -s -X POST "${BASE}/api/council/stream" \
        -H "Content-Type: application/json" \
        -d "{\"topic\": \"$TASK\", \"rounds\": 1}" 2>/dev/null | \
        grep "member_message" | python3 -c "
import json, sys
members = []
for line in sys.stdin:
    try:
        d = json.loads(line.strip().replace('data: ', ''))
        if d.get('type') == 'member_message':
            members.append({
                'emoji': d.get('emoji', ''),
                'name': d.get('name', '?'),
                'agent_id': d.get('agent', '?'),
                'content': d.get('content', '')[:300],
                'elapsed': d.get('elapsed', 0),
                'provider': d.get('provider', '?')
            })
    except: pass
for m in members:
    print(f\"### {m['emoji']} {m['name']} ({m['elapsed']:.1f}s)\")
    print()
    print(m['content'])
    print()
" 2>/dev/null)
    
    if [ -n "$RESPONSE" ]; then
        echo "$RESPONSE" | tee -a "$REPORT"
        SUCCESS=$((SUCCESS+1))
        echo -e "${G}✅ نجح${N}"
        STATUS="ok"
    else
        echo -e "${R}❌ فشل${N}"
        echo "❌ فشل" >> "$REPORT"
        FAIL=$((FAIL+1))
        STATUS="fail"
    fi
    
    echo "" >> "$REPORT"
    echo "---" >> "$REPORT"
    echo "" >> "$REPORT"
    
    # JSON
    if [ "$FIRST_BM" = false ]; then
        echo "," >> "$JSON_REPORT"
    fi
    FIRST_BM=false
    echo "    {\"benchmark\": \"$BENCH\", \"status\": \"$STATUS\", \"timestamp\": $(date +%s)}" >> "$JSON_REPORT"
    
    # انتظر
    sleep 6
done

echo "  ]" >> "$JSON_REPORT"
echo "}" >> "$JSON_REPORT"

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

# ═══ Genome بعد الاختبار ═══
GENOME=$(curl -s ${BASE}/api/genome 2>/dev/null)

{
    echo ""
    echo "---"
    echo ""
    echo "## 📊 Genome بعد الاختبار"
    echo ""
    echo '```json'
    echo "$GENOME" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    for a in sorted(d.get('agents', []), key=lambda x: -x.get('standing', 0)):
        name = a.get('agent_id', '?')
        st = a.get('standing', 0) * 100
        runs = a.get('runs', 0)
        status = a.get('status', '?')
        print(f\"{name:12s} | {st:5.1f}% | {status:10s} | runs={runs}\")
except Exception as e:
    print(f'خطأ: {e}')
" 2>/dev/null
    echo '```'
    echo ""
    echo "## 📊 الملخص"
    echo ""
    echo "- **إجمالي المعايير:** ${#BENCHMARKS[@]}"
    echo "- **نجح:** $SUCCESS"
    echo "- **فشل:** $FAIL"
    echo "- **المدة:** $((DURATION/60))د $((DURATION%60))ث"
    echo ""
    echo "**اكتمل:** $(date)"
} >> "$REPORT"

line
title "  ✅ اكتمل الاختبار"
line
echo ""
log "✅ نجح: $SUCCESS"
log "❌ فشل: $FAIL"
log "⏱️  المدة: $((DURATION/60))د $((DURATION%60))ث"
log "📄 التقرير: $REPORT"
log "📊 JSON: $JSON_REPORT"
echo ""

# Genome النهائي
echo -e "${C}═══ Genome بعد الاختبار ═══${N}"
curl -s ${BASE}/api/genome 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    for a in sorted(d.get('agents', []), key=lambda x: -x.get('standing', 0)):
        emoji = a.get('meta', {}).get('emoji', '🤖')
        name = a.get('agent_id', '?')
        st = a.get('standing', 0) * 100
        runs = a.get('runs', 0)
        status = a.get('status', '?')
        print(f'  {emoji} {name:12s} | {st:5.1f}% | {status:10s} | runs={runs}')
except Exception as e:
    print(f'خطأ: {e}')
" 2>/dev/null
echo ""
