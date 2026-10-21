#!/bin/bash
# ═══════════════════════════════════════════════════════════
# CI Simulator — Replicates GitHub Actions environment locally
# ═══════════════════════════════════════════════════════════
set -e  # Exit on first error (like CI)

# ═══════════════════════════════════════════════════════════
# [1] Setup environment (like GitHub Actions)
# ═══════════════════════════════════════════════════════════
SIM_DIR="${SIM_DIR:-/tmp/ci_simulate}"
WORKSPACE="$SIM_DIR/workspace"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"

echo "═══════════════════════════════════════════════════════════"
echo "  CI Simulator — Python $PYTHON_VERSION"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Clean
rm -rf "$SIM_DIR"
mkdir -p "$WORKSPACE"

# Copy project (like actions/checkout)
cp -r /public/agent/novamind/* "$WORKSPACE/" 2>/dev/null || true
cp -r /public/agent/novamind/.[!.]* "$WORKSPACE/" 2>/dev/null || true

cd "$WORKSPACE"

# Remove .env (simulate CI — .env is gitignored)
rm -f .env

# Set CI environment variables (like GitHub Actions)
export GITHUB_ACTIONS=true
export GITHUB_WORKSPACE="$WORKSPACE"
export NOVAMIND_HOME="$WORKSPACE"
export PYTHONUNBUFFERED=1
export CI=true

# Unset local overrides
unset GEMINI_API_KEY
unset GROQ_API_KEY
unset PYTHONPATH

echo "✅ Environment set up"
echo "   WORKSPACE: $WORKSPACE"
echo "   Python: $(python3 --version)"
echo ""

# ═══════════════════════════════════════════════════════════
# [2] Verify NOVAMIND_HOME
# ═══════════════════════════════════════════════════════════
echo "═══════════════════════════════════════════════════════════"
echo "  Step: Verify NOVAMIND_HOME"
echo "═══════════════════════════════════════════════════════════"
echo "NOVAMIND_HOME=$NOVAMIND_HOME"
pwd
ls -la | head -10
echo "✅ Verify NOVAMIND_HOME passed"
echo ""

# ═══════════════════════════════════════════════════════════
# [3] Syntax check all Python files
# ═══════════════════════════════════════════════════════════
echo "═══════════════════════════════════════════════════════════"
echo "  Step: Syntax check all Python files"
echo "═══════════════════════════════════════════════════════════"
python3 -c "
import ast, sys
from pathlib import Path
errors = []
for p in Path('.').rglob('*.py'):
    if any(x in str(p) for x in ['.git', '__pycache__', 'venv']):
        continue
    try:
        ast.parse(p.read_text(encoding='utf-8', errors='ignore'))
    except SyntaxError as e:
        errors.append(f'{p}: {e}')
if errors:
    print('SYNTAX ERRORS:')
    for e in errors[:20]:
        print(' -', e)
    sys.exit(1)
print('✅ All Python files have valid syntax')
"
echo ""

# ═══════════════════════════════════════════════════════════
# [4] Set NOVAMIND_HOME to workspace (create dirs)
# ═══════════════════════════════════════════════════════════
echo "═══════════════════════════════════════════════════════════"
echo "  Step: Set NOVAMIND_HOME and create dirs"
echo "═══════════════════════════════════════════════════════════"
mkdir -p "$NOVAMIND_HOME/memory/providers"
mkdir -p "$NOVAMIND_HOME/memory/vector_store"
mkdir -p "$NOVAMIND_HOME/memory/knowledge_graph"
mkdir -p "$NOVAMIND_HOME/memory/projects"
mkdir -p "$NOVAMIND_HOME/logs"
mkdir -p "$NOVAMIND_HOME/workspace"
mkdir -p "$NOVAMIND_HOME/data"
echo "✅ Created directories:"
ls -la "$NOVAMIND_HOME/memory"
echo ""

# ═══════════════════════════════════════════════════════════
# [5] Test path resolution
# ═══════════════════════════════════════════════════════════
echo "═══════════════════════════════════════════════════════════"
echo "  Step: Test path resolution"
echo "═══════════════════════════════════════════════════════════"
python3 -c "
import sys, os
sys.path.insert(0, '.')
from core.settings import settings
print(f'Environment: {settings.environment}')
print(f'HOME: {settings.novamind_home}')
print(f'MEMORY: {settings.memory_dir}')
print(f'VECTOR: {settings.vector_store_dir}')
assert settings.novamind_home.exists(), 'Home must exist'
assert settings.memory_dir.exists(), 'Memory must exist'
print('✅ Paths work')
"
echo ""

# ═══════════════════════════════════════════════════════════
# [6] Debug - factory errors
# ═══════════════════════════════════════════════════════════
echo "═══════════════════════════════════════════════════════════"
echo "  Step: Debug - factory errors"
echo "═══════════════════════════════════════════════════════════"
python3 -c "
import sys
sys.path.insert(0, '.')
from agents.factory import AgentFactory
f = AgentFactory()
avail = f.list_available()
print(f'Available: {len(avail)}/52')
if f._errors:
    print(f'Errors: {f._errors}')
else:
    print('Errors: {}')
"
echo ""

# ═══════════════════════════════════════════════════════════
# [7] Run tests
# ═══════════════════════════════════════════════════════════
echo "═══════════════════════════════════════════════════════════"
echo "  Step: Run tests"
echo "═══════════════════════════════════════════════════════════"
python3 -m pytest tests/ -v --tb=short --no-header
echo ""

# ═══════════════════════════════════════════════════════════
# [8] Summary
# ═══════════════════════════════════════════════════════════
echo "═══════════════════════════════════════════════════════════"
echo "  ✅ CI SIMULATION PASSED"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Environment:"
echo "  NOVAMIND_HOME: $NOVAMIND_HOME"
echo "  Python: $(python3 --version)"
echo "  Workspace: $WORKSPACE"
echo ""
