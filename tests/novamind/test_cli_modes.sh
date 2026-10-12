#!/bin/sh
echo "═══════════════════════════════════════════════"
echo "  CLI Modes Test"
echo "═══════════════════════════════════════════════"
echo ""

PASS=0; FAIL=0

test_mode() {
    MODE="$1"
    if timeout 15 python3 novamind.py "$MODE" > /dev/null 2>&1; then
        echo "  ✅ $MODE"
        PASS=$((PASS+1))
    else
        echo "  ❌ $MODE"
        FAIL=$((FAIL+1))
    fi
}

echo "🎯 Testing modes:"
test_mode "help"
test_mode "status"
test_mode "army-status"
test_mode "army-roles"
test_mode "army-soldiers"
echo ""

echo "═══════════════════════════════════════════════"
echo "  PASS: $PASS  |  FAIL: $FAIL"
echo "═══════════════════════════════════════════════"
