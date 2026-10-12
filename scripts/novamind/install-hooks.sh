#!/bin/bash
# Install Git hooks for NovaMind-Hive
# Usage: bash scripts/install-hooks.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
HOOKS_SRC="$SCRIPT_DIR/git-hooks"
HOOKS_DST="$PROJECT_ROOT/.git/hooks"

if [ ! -d "$HOOKS_SRC" ]; then
    echo "Error: $HOOKS_SRC not found"
    exit 1
fi

if [ ! -d "$HOOKS_DST" ]; then
    echo "Error: $HOOKS_DST not found - is this a git repository?"
    exit 1
fi

INSTALLED=0
for hook in "$HOOKS_SRC"/*; do
    if [ -f "$hook" ]; then
        hook_name=$(basename "$hook")
        cp "$hook" "$HOOKS_DST/$hook_name"
        chmod +x "$HOOKS_DST/$hook_name"
        echo "  Installed: $hook_name"
        INSTALLED=$((INSTALLED + 1))
    fi
done

echo ""
echo "Done. Installed $INSTALLED hook(s)."
