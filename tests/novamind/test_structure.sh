#!/bin/sh
# NovaMind — Structure Audit

echo "═══════════════════════════════════════════════"
echo "  Structure Audit"
echo "═══════════════════════════════════════════════"
echo ""

PASS=0; FAIL=0

check() {
    if [ "$1" = "ok" ]; then
        echo "  ✅ $2"
        PASS=$((PASS+1))
    else
        echo "  ❌ $2"
        FAIL=$((FAIL+1))
    fi
}

# 1. Core files
echo "📁 [1] Core Files"
[ -f "novamind.py" ] && check ok "novamind.py" || check fail "novamind.py"
[ -f "VERSION" ] && check ok "VERSION ($(cat VERSION))" || check fail "VERSION"
[ -f "README.md" ] && check ok "README.md" || check fail "README.md"
[ -f "LICENSE" ] && check ok "LICENSE" || check fail "LICENSE"
[ -f ".gitignore" ] && check ok ".gitignore" || check fail ".gitignore"
[ -f "requirements.txt" ] && check ok "requirements.txt" || check fail "requirements.txt"
echo ""

# 2. Core structure
echo "📁 [2] Core Structure"
[ -d "core" ] && check ok "core/" || check fail "core/"
[ -d "core/company" ] && check ok "core/company/ ($(ls core/company/*.py 2>/dev/null | wc -l) files)" || check fail "core/company/"
[ -d "core/providers" ] && check ok "core/providers/ ($(ls core/providers/*.py 2>/dev/null | wc -l) files)" || check fail "core/providers/"
[ -d "agent" ] && check ok "agent/" || check fail "agent/"
[ -d "data" ] && check ok "data/" || check fail "data/"
echo ""

# 3. Data files
echo "📁 [3] Data Files"
[ -f "data/company/constitution.json" ] && check ok "constitution.json" || check fail "constitution.json"
[ -f "data/company/genome.json" ] && check ok "genome.json" || check fail "genome.json"
[ -f "data/company/reputation.json" ] && check ok "reputation.json" || check fail "reputation.json"
[ -f "data/company/costs.json" ] && check ok "costs.json" || check fail "costs.json"
echo ""

# 4. Syntax
echo "📁 [4] Python Syntax"
python3 -c "import ast; ast.parse(open('novamind.py').read())" 2>/dev/null && check ok "novamind.py syntax" || check fail "novamind.py syntax"
echo ""

# 5. Git
echo "📁 [5] Git"
[ -d ".git" ] && check ok ".git exists" || check fail ".git"
TRACKED=$(git ls-files 2>/dev/null | wc -l)
check ok "$TRACKED tracked files"
KEYS=$(git log --all -S "REDACTED" --oneline 2>/dev/null | wc -l)
[ "$KEYS" -eq 0 ] && check ok "No keys in history" || check fail "$KEYS commits with keys"
echo ""

echo "═══════════════════════════════════════════════"
echo "  PASS: $PASS  |  FAIL: $FAIL"
echo "═══════════════════════════════════════════════"
