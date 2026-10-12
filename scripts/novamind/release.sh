#!/bin/bash
# Release new version
set -e
if [ -z "$1" ]; then
    echo "Usage: $0 <version>"
    echo "Example: $0 3.5.0"
    exit 1
fi
VERSION="v$1"
echo "🚀 Creating release $VERSION..."
git tag -a "$VERSION" -m "Release $VERSION"
git push origin "$VERSION"
echo "✅ Released $VERSION"
