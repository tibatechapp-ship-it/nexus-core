#!/bin/sh
# NovaMind — Verification Script
# Usage: ./verify.sh

echo "═══════════════════════════════════════════════════════════"
echo "  NovaMind — Verification"
echo "  Date: $(date)"
echo "═══════════════════════════════════════════════════════════"
echo ""

VERBOSE=0
[ "$1" = "-v" ] && VERBOSE=1

# ═══ 1. Git integrity ═══
echo "🔍 [1/5] Git integrity..."
git status --short 2>/dev/null | head -5
echo ""

# ═══ 2. VERSION ═══
echo "🔍 [2/5] Version check..."
if [ -f VERSION ]; then
    echo "   ✅ VERSION: $(cat VERSION)"
else
    echo "   ❌ VERSION missing"
fi
echo ""

# ═══ 3. Required files ═══
echo "🔍 [3/5] Required files..."
MISSING=""

for f in core/llm_router.py core/company/supreme.py agent/novamind_bot.py; do
    [ ! -f "$f" ] && MISSING="$MISSING $f"
done

if [ -z "$MISSING" ]; then
    echo "   ✅ All required files present"
else
    echo "   ❌ Missing:$MISSING"
fi
echo ""

# ═══ 4. Manifest checksum ═══
echo "🔍 [4/5] Manifest..."
if [ -f MANIFEST.txt ]; then
    TOTAL=$(grep -c "^[a-f0-9]" MANIFEST.txt)
    echo "   ✅ MANIFEST: $TOTAL files"
    
    # تحقق من عيّنة
    if [ $VERBOSE -eq 1 ]; then
        echo "   Sample verification:"
        grep "^[a-f0-9]" MANIFEST.txt | head -5 | while read hash size file; do
            actual=$(sha256sum "$file" 2>/dev/null | cut -c1-16)
            if [ "$actual" = "$hash" ]; then
                echo "     ✅ $file"
            else
                echo "     ❌ $file (expected $hash, got $actual)"
            fi
        done
    fi
else
    echo "   ❌ MANIFEST.txt missing"
fi
echo ""

# ═══ 5. Import test ═══
echo "🔍 [5/5] Import test..."
python3 -c "
import sys
sys.path.insert(0, '.')
from core.llm_router import LLMRouter
from core.company.supreme import SupremeCouncil
print('   ✅ Critical modules import OK')
" 2>&1 | head -3
echo ""

echo "═══════════════════════════════════════════════════════════"
echo "  ✅ Verification Complete"
echo "═══════════════════════════════════════════════════════════"
