#!/bin/sh
FILE="$1"

if [ ! -f "$FILE" ]; then
    echo "MISSING: $FILE"
    exit 1
fi

echo "=== CHECKING: $FILE ==="
echo "Size: $(wc -c < "$FILE") bytes"
echo "Lines: $(wc -l < "$FILE") lines"
echo ""

echo "--- First 5 lines ---"
head -5 "$FILE"
echo ""

if echo "$FILE" | grep -q "\.py$"; then
    if python3 -c "import ast; ast.parse(open('$FILE').read())" 2>/dev/null; then
        echo "SYNTAX OK"
    else
        echo "SYNTAX ERROR:"
        python3 -c "import ast; ast.parse(open('$FILE').read())" 2>&1 | head -5
    fi
fi
