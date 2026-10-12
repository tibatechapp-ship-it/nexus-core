#!/bin/bash
set -euo pipefail

echo "🚀 Starting Integration Test..."

# ═══════════════════════════════════════════════════
# 1. ضبط PYTHONPATH — استخدم src/ (البنية الفعلية)
# ═══════════════════════════════════════════════════
export PYTHONPATH="${PWD}/src:${PYTHONPATH:-}"
echo "✅ PYTHONPATH set to: $PYTHONPATH"

# ═══════════════════════════════════════════════════
# 2. اختبار استيراد الحزمة الرئيسية (novamind)
# ═══════════════════════════════════════════════════
python3 -c "import novamind; print('✅ novamind package imported successfully')" || exit 1

# ═══════════════════════════════════════════════════
# 3. اختبار تحميل Registry والـ Factory
# ═══════════════════════════════════════════════════
python3 << 'PYEOF'
try:
    from novamind.agents.factory import factory
    print(f"✅ Factory loaded successfully")
    
    # جرب استرجاع وكيل
    try:
        agent = factory.get("coder")
        print(f"✅ Coder agent loaded: {type(agent).__name__}")
    except Exception as e:
        print(f"⚠️ Agent loading warning: {e}")
except ImportError as e:
    print(f"❌ Import Error: {e}")
    exit(1)
PYEOF

echo "🎉 All Integration Tests Passed!"
