"""Config — runtime constants for novamind."""
import os
from pathlib import Path

EXECUTE_TIMEOUT = int(os.environ.get("EXECUTE_TIMEOUT", "300"))
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "/tmp/novamind_workspace"))
MAX_FIX_ATTEMPTS = int(os.environ.get("MAX_FIX_ATTEMPTS", "3"))
