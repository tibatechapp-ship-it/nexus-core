"""Embedding Agent — Detects embedding/vector search issues."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.embedding_agent")


class EmbeddingAgent:

    def __init__(self):
        self.name = "embedding"
    """Detects embedding issues."""

    PATTERNS = {
        "dimension": [
            (r'dimensions?\s*=\s*(?:3|4|8|16)\b', "Very small embedding dimension"),
            (r'dimensions?\s*=\s*\d{5,}', "Very large embedding dimension"),
        ],
        "similarity": [
            (r'cosine.*dot.*product', "Mixing cosine and dot — verify normalization"),
            (r'euclidean.*normalize', "Euclidean on normalized — use cosine"),
        ],
        "chunking": [
            (r'chunk_size\s*=\s*\d{5,}', "Very large chunk size"),
            (r'chunk_overlap\s*=\s*0\b', "No overlap — context loss"),
        ],
        "indexing": [
            (r'index.*flat.*\d{6,}', "Flat index on large data — use IVF/HNSW"),
        ],
        "tokenization": [
            (r'tokenize\s*\([^)]*\)[^;]*\n[^}]*embed', "Consider batch tokenization"),
        ],
    }

    def analyze(self, code: str, filename: str = "") -> Dict:
        if not code:
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        issues = []
        lines = code.split("\n")

        for category, patterns in self.PATTERNS.items():
            for pattern, desc in patterns:
                try:
                    regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
                except re.error:
                    continue
                for i, line in enumerate(lines, 1):
                    if line.strip().startswith(("#", "//")):
                        continue
                    if regex.search(line):
                        issues.append({
                            "line": i,
                            "category": category,
                            "severity": "medium",
                            "description": desc,
                            "snippet": line.strip()[:100],
                        })

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


embedding_agent = EmbeddingAgent()
__all__ = ["EmbeddingAgent", "embedding_agent"]
