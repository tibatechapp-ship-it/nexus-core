#!/bin/sh
# كشف إذا كان الأمر الأخير في history نفس الجديد
LAST=$(fc -ln -1 2>/dev/null | head -1 | xargs)
CURRENT="$*"
if [ "$LAST" = "$CURRENT" ]; then
  echo "⚠️  Duplicate command blocked: $CURRENT"
  exit 1
fi
