#!/usr/bin/env python3
"""Generate SHA256 manifest for critical files."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent

CRITICAL_DIRS = [
    ROOT / "src" / "novamind" / "core",
    ROOT / "src" / "novamind" / "security",
    ROOT / "src" / "novamind" / "factory",
]

manifest = {}

for directory in CRITICAL_DIRS:
    if not directory.exists():
        continue
    for f in sorted(directory.rglob("*.py")):
        if "__pycache__" in str(f):
            continue
        rel = str(f.relative_to(ROOT))
        content = f.read_bytes()
        manifest[rel] = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        }

output = ROOT / ".build-meta" / "manifest.json"
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(manifest, indent=2, sort_keys=True))

print(f"✅ Manifest generated: {len(manifest)} files")
print(f"   → {output.relative_to(ROOT)}")
