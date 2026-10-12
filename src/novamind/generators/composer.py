"""Code Composer — يجمع ناتج المولّدات ويكتبها على القرص."""
from __future__ import annotations
from pathlib import Path
from typing import List, Dict
from datetime import datetime, timezone
import hashlib
import json

from hive.generators.contract import GeneratedPart


class Composer:
    def __init__(self, output_dir: Path, overwrite: bool = True):
        self.output_dir = Path(output_dir)
        self.overwrite = overwrite
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.manifest: Dict = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "files": {},
            "generators": [],
        }

    def compose(self, parts: List[GeneratedPart], dry_run: bool = False) -> Dict:
        all_files: Dict[str, str] = {}
        conflicts: List[Dict] = []

        for part in parts:
            self.manifest["generators"].append({
                "name": part.generator_name,
                "files": len(part.files),
                "metadata": part.metadata,
            })
            for f in part.files:
                if f.path in all_files and all_files[f.path] != f.content:
                    conflicts.append({
                        "path": f.path,
                        "generators": ["<existing>", part.generator_name],
                    })
                    continue
                all_files[f.path] = f.content

        if conflicts:
            raise ValueError(f"تعارض ملفات: {conflicts}")

        if dry_run:
            return {
                "dry_run": True,
                "would_write": list(all_files.keys()),
                "count": len(all_files),
            }

        written = []
        skipped = []
        for rel_path, content in all_files.items():
            full = self.output_dir / rel_path
            full.parent.mkdir(parents=True, exist_ok=True)

            if full.exists() and not self.overwrite:
                skipped.append(rel_path)
                continue

            full.write_text(content, encoding="utf-8")
            self.manifest["files"][rel_path] = {
                "hash": hashlib.sha256(content.encode()).hexdigest()[:16],
                "size": len(content),
            }
            written.append(rel_path)

        # اكتب manifest
        manifest_path = self.output_dir / ".novamind_manifest.json"
        manifest_path.write_text(
            json.dumps(self.manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        return {
            "written": written,
            "skipped": skipped,
            "count": len(written),
            "manifest": str(manifest_path),
        }
