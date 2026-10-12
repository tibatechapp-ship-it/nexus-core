#!/usr/bin/env python3
"""Generate build integrity hash for release."""
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent

def compute_tree_hash(path: Path) -> str:
    """Deterministic hash of directory tree."""
    hasher = hashlib.sha256()
    
    for f in sorted(path.rglob("*")):
        if not f.is_file():
            continue
        if "__pycache__" in str(f):
            continue
        if f.suffix in {".pyc", ".pyo"}:
            continue
        
        # Hash relative path + content
        rel = str(f.relative_to(ROOT))
        hasher.update(rel.encode("utf-8"))
        hasher.update(f.read_bytes())
    
    return hasher.hexdigest()

def main():
    tree_hash = compute_tree_hash(ROOT / "src" / "novamind")
    
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tree_hash": tree_hash,
        "commit": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=ROOT
        ).stdout.strip(),
        "version": "3.4.0",
    }
    
    output = ROOT / ".build-meta" / "integrity.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(meta, indent=2))
    
    print(f"✅ Integrity hash: {tree_hash[:16]}...")
    print(f"   Saved to: {output.relative_to(ROOT)}")

if __name__ == "__main__":
    main()
