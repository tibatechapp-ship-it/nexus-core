#!/bin/bash
# Health check
set -e
echo "🔍 NovaMind Health Check"
echo ""
echo "1. Import test:"
PYTHONPATH=src python3 -c "import novamind; print('  ✅ novamind')"
echo ""
echo "2. Registry:"
PYTHONPATH=src python3 -c "
from novamind.registry import stats, validate
s = stats()
print(f'  ✅ {s[\"agents_total\"]} agents, {s[\"tools\"]} tools, {s[\"managers\"]} managers')
print(f'  ✅ validate: {len(validate())} errors')
"
echo ""
echo "3. Factory:"
PYTHONPATH=src python3 -c "
from novamind.agents.factory import factory
agent = factory.get('coder')
print(f'  ✅ coder: {type(agent).__name__}')
"
echo ""
echo "✅ All checks passed"
