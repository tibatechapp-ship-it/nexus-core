#!/data/data/com.termux/files/usr/bin/bash
# Called when a task completes.
# Usage: on-task-complete.sh "task name" "status" "duration"

TASK_NAME="${1:-Unknown Task}"
STATUS="${2:-completed}"
DURATION="${3:-0s}"

# Collect info
cd ~/nexus-core 2>/dev/null

LAST_COMMIT=$(git log -1 --pretty=format:"%h" 2>/dev/null || echo "n/a")
BRANCH=$(git branch --show-current 2>/dev/null || echo "n/a")
FILES=$(git diff --name-only HEAD~1 HEAD 2>/dev/null | head -20 || echo "")

# Build message
python3 << PYEOF
import sys
sys.path.insert(0, "$HOME/nexus-core/reports")
from vixona_report import report_task_complete

report_task_complete(
    task_name="""$TASK_NAME""",
    status="""$STATUS""",
    files="""$FILES""".strip().split("\n") if """$FILES""".strip() else [],
    duration="""$DURATION""",
    notes=f"Branch: $BRANCH | Commit: $LAST_COMMIT",
)
PYEOF
