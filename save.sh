#!/bin/bash
cd /public
git add -A
git commit -m "brain: session $(date +%Y-%m-%d_%H:%M)" 2>/dev/null || true
git push origin $(git branch --show-current) 2>/dev/null || echo "Push deferred"
echo "محفوظ"
