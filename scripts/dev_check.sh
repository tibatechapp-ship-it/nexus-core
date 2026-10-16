#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> ruff check"
ruff check .

echo "==> mypy (framework scope)"
mypy zyvo-telegram.py zyvo-voice.py src

echo "==> check_annotations"
python scripts/check_annotations.py

echo "==> pytest --cov (canonical gate: coverage floor 95%, novamind excluded)"
pytest --cov --cov-fail-under=95 --ignore=tests/novamind -q

echo "==> ALL GREEN"
