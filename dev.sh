#!/bin/sh
# ═══════════════════════════════════════════════════════
# NovaMind — dev.sh
# كل أوامر التطوير في مكان واحد
# Usage: sh dev.sh <command>
# ═══════════════════════════════════════════════════════
set -e

CMD="${1:-help}"

case "$CMD" in
  test)
    echo "🧪 Tests..."
    PYTHONPATH=src python3 -m pytest tests/ -q --tb=short
    ;;

  test-full)
    echo "🧪 Full tests with coverage..."
    PYTHONPATH=src python3 -m pytest tests/ --tb=short -v
    ;;

  status)
    echo "═══ Git Status ═══"
    git status --short
    echo ""
    echo "═══ Last 5 commits ═══"
    git log --oneline -5
    echo ""
    echo "═══ Branch ═══"
    git branch --show-current
    ;;

  agents)
    echo "🤖 Registry + Agents..."
    PYTHONPATH=src python3 -c "
from novamind.registry import stats, all_agent_names, all_pipeline_ids
from novamind.agents.factory import factory
s = stats()
print(f'Agents: {s[\"agents_total\"]}')
print(f'Tools: {s[\"tools\"]}, Managers: {s[\"managers\"]}')
print(f'Pipelines: {all_pipeline_ids()}')
loaded = sum(1 for n in all_agent_names() if factory.get(n))
print(f'Loaded: {loaded}/{s[\"agents_total\"]}')
"
    ;;

  cmd)
    echo "🎯 Commander smoke test..."
    PYTHONPATH=src python3 -c "
from novamind.commander import Commander
c = Commander()
for task in ['fix login bug', 'deploy to production', 'review code', 'create module']:
    print(f'  {task:25s} → {c.choose_pipeline(task)}')
"
    ;;

  check)
    echo "🔍 Syntax check..."
    PYTHONPATH=src python3 -c "
import ast
from pathlib import Path
bad = []
for p in Path('src/novamind').rglob('*.py'):
    try:
        ast.parse(p.read_text(encoding='utf-8'))
    except SyntaxError as e:
        bad.append((p, e.lineno, e.msg))
if bad:
    print(f'❌ {len(bad)} files with syntax errors:')
    for f, ln, msg in bad[:10]:
        print(f'  {f}:{ln}: {msg}')
    exit(1)
print('✅ All syntax OK')
"
    ;;

  clean)
    echo "🧹 Cleaning cache..."
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    echo "✅ Clean"
    ;;

  backup)
    echo "💾 Creating backup..."
    TS=$(date +%Y%m%d-%H%M%S)
    mkdir -p exports
    git bundle create "exports/novamind-$TS.bundle" --all
    git archive --format=tar.gz --output="exports/novamind-$TS.tar.gz" HEAD
    echo "✅ Backup: exports/novamind-$TS.{bundle,tar.gz}"
    ;;

  tag)
    if [ -z "$2" ]; then
      echo "Usage: sh dev.sh tag v3.2.0"
      exit 1
    fi
    git tag -a "$2" -m "NovaMind $2"
    git push origin "$2"
    echo "✅ Tag $2 pushed"
    ;;

  merge)
    echo "🔀 Merging to main..."
    git checkout main
    git merge feat/commander-v3 --no-edit
    git push origin main
    git checkout feat/commander-v3
    echo "✅ Merged to main"
    ;;

  fix-indent)
    echo "🔧 Fixing indentation issues..."
    python3 << 'PYEOF'
from pathlib import Path
import ast

fixed = []
for p in Path('src/novamind').rglob('*.py'):
    try:
        ast.parse(p.read_text(encoding='utf-8'))
    except SyntaxError as e:
        if 'unexpected indent' in str(e.msg):
            print(f"  ⚠️  {p}:{e.lineno}")
            fixed.append(p)
if not fixed:
    print("✅ No indent issues found")
else:
    print(f"Found {len(fixed)} files — manual fix needed")
PYEOF
    ;;

  install-check)
    echo "📦 Testing pip install -e . ..."
    python3 -c "
from novamind.commander import Commander
from novamind.registry import all_pipeline_ids
print('✅ novamind importable without PYTHONPATH')
print('Pipelines:', all_pipeline_ids())
c = Commander()
print('Commander:', c.choose_pipeline('fix bug'))
"
    ;;

  help|*)
    cat << 'HELP'

╔══════════════════════════════════════════════════╗
║         NovaMind — dev.sh commands               ║
╠══════════════════════════════════════════════════╣
║  test         اختبارات سريعة                     ║
║  test-full    اختبارات كاملة + تفاصيل            ║
║  status       git status + آخر commits           ║
║  agents       إحصاءات الوكلاء + pipelines        ║
║  cmd          اختبار Commander                   ║
║  check        فحص syntax لكل الملفات             ║
║  clean        حذف __pycache__                    ║
║  backup       bundle + tar.gz في exports/        ║
║  tag X.Y.Z    إنشاء tag + push                   ║
║  merge        merge feat → main                  ║
║  fix-indent   كشف مشاكل indent                   ║
╚══════════════════════════════════════════════════╝
HELP
    ;;
esac
