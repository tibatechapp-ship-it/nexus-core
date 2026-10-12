#!/bin/sh
# NovaMind — unified runner
# Usage: sh run.sh <command>

set -e

case "$1" in
  test)
    PYTHONPATH=src python3 -m pytest tests/ -q --tb=short
    ;;
  cmd)
    PYTHONPATH=src python3 -c "
from novamind.commander import Commander
cmd = Commander()
print('✅ Commander loaded')
print('  fix bug →', cmd.choose_pipeline('fix login bug'))
print('  deploy  →', cmd.choose_pipeline('deploy to production'))
print('  review  →', cmd.choose_pipeline('review code quality'))
"
    ;;
  fix-registry)
    python3 << 'PYEOF'
from pathlib import Path
core = Path("src/novamind/registry/core.py")
text = core.read_text(encoding="utf-8")
if "def all_pipeline_ids" not in text:
    text += '''

# ═══ Pipelines API ═══
def all_pipeline_ids() -> list:
    """أسماء كل pipelines."""
    data = load_registry()
    return list(data.get("pipelines", {}).keys())


def all_pipelines() -> dict:
    """كل pipelines مع تفاصيلها."""
    data = load_registry()
    return dict(data.get("pipelines", {}))


def pipeline(pipeline_id: str):
    """تفاصيل pipeline واحد."""
    data = load_registry()
    return data.get("pipelines", {}).get(pipeline_id)
'''
    core.write_text(text, encoding="utf-8")
    print("✅ core.py updated")

init = Path("src/novamind/registry/__init__.py")
itext = init.read_text(encoding="utf-8")
if "all_pipeline_ids" not in itext:
    # أضف سطر التصدير بعد آخر from .core import
    itext += "\nfrom novamind.registry.core import all_pipeline_ids, all_pipelines, pipeline\n"
    init.write_text(itext, encoding="utf-8")
    print("✅ __init__.py updated")
PYEOF
    ;;
  *)
    echo "Usage: sh run.sh {test|cmd|fix-registry}"
    ;;
esac
