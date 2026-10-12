#!/bin/bash
# Sync with remote
set -e
echo "🔄 Syncing with origin/main..."
git fetch origin --prune
git pull origin main
echo "✅ Synced"
