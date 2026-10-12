"""
Vector Store — Lightweight semantic search using TF-IDF.
No heavy dependencies (no numpy, no chromadb required).
"""
import json
import math
import re
import logging
from pathlib import Path
from collections import Counter
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timezone

logger = logging.getLogger("core.rag.vector_store")

from novamind.core.settings import VECTOR_STORE_DIR as STORE_DIR


class TFIDFVectorizer:
    """Simple TF-IDF vectorizer (pure Python)."""
    
    def __init__(self):
        self.vocab = {}
        self.idf = {}
        self.doc_count = 0
    
    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text with light stemming (supports Arabic + English)."""
        text = text.lower()
        # Extract words (including Arabic)
        words = re.findall(r'[a-z\u0600-\u06FF_][a-z0-9\u0600-\u06FF_]*', text)

        # Light English stemming + expand tokens
        expanded = []
        for w in words:
            expanded.append(w)
            # Add stem for common suffixes
            if len(w) > 5:
                if w.endswith("tion"):
                    expanded.append(w[:-4])
                elif w.endswith("ing"):
                    expanded.append(w[:-3])
                elif w.endswith("ed"):
                    expanded.append(w[:-2])
                elif w.endswith("er") or w.endswith("or"):
                    expanded.append(w[:-2])
                elif w.endswith("ly"):
                    expanded.append(w[:-2])
                elif w.endswith("s") and not w.endswith("ss"):
                    expanded.append(w[:-1])

        return expanded
    
    def fit(self, documents: List[str]):
        """Build vocabulary and IDF from documents."""
        self.doc_count = len(documents)
        doc_freq = Counter()
        
        for doc in documents:
            tokens = set(self._tokenize(doc))
            for t in tokens:
                doc_freq[t] += 1
        
        # Build vocab
        self.vocab = {term: idx for idx, term in enumerate(sorted(doc_freq.keys()))}
        
        # Compute IDF
        for term, freq in doc_freq.items():
            self.idf[term] = math.log((self.doc_count + 1) / (freq + 1)) + 1
    
    def transform(self, text: str) -> Dict[int, float]:
        """Convert text to sparse TF-IDF vector."""
        tokens = self._tokenize(text)
        if not tokens:
            return {}
        
        tf = Counter(tokens)
        max_tf = max(tf.values()) if tf else 1
        
        vector = {}
        for term, count in tf.items():
            if term not in self.vocab:
                continue
            idx = self.vocab[term]
            tf_norm = 0.5 + 0.5 * (count / max_tf)
            idf = self.idf.get(term, 1.0)
            vector[idx] = tf_norm * idf
        
        return vector
    
    @staticmethod
    def cosine_similarity(v1: Dict[int, float], v2: Dict[int, float]) -> float:
        """Cosine similarity between sparse vectors."""
        if not v1 or not v2:
            return 0.0
        
        # Dot product
        dot = 0.0
        for k, v in v1.items():
            if k in v2:
                dot += v * v2[k]
        
        # Norms
        n1 = math.sqrt(sum(v * v for v in v1.values()))
        n2 = math.sqrt(sum(v * v for v in v2.values()))
        
        if n1 == 0 or n2 == 0:
            return 0.0
        
        return dot / (n1 * n2)


class VectorStore:
    """Store code snippets with semantic search."""
    
    def __init__(self, name: str = "default"):
        self.name = name
        self.file = STORE_DIR / f"{name}.json"
        self.documents: List[Dict] = []
        self.vectorizer = TFIDFVectorizer()
        self._vectors: List[Dict[int, float]] = []
        self._load()
    
    def _load(self):
        if self.file.exists():
            try:
                data = json.loads(self.file.read_text(encoding="utf-8"))
                self.documents = data.get("documents", [])
                self._rebuild()
            except Exception as e:
                logger.warning(f"load failed: {e}")
    
    def _save(self):
        try:
            self.file.write_text(
                json.dumps({"documents": self.documents}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"save failed: {e}")
    
    def _rebuild(self):
        """Rebuild vectors from documents."""
        if not self.documents:
            return
        texts = [d["text"] for d in self.documents]
        self.vectorizer.fit(texts)
        self._vectors = [self.vectorizer.transform(t) for t in texts]
    
    def add(self, text: str, metadata: Optional[Dict] = None,
            doc_id: Optional[str] = None) -> str:
        """Add a document."""
        doc_id = doc_id or f"doc_{len(self.documents)}_{int(datetime.now(timezone.utc).timestamp())}"
        
        self.documents.append({
            "id": doc_id,
            "text": text,
            "metadata": metadata or {},
            "added_at": datetime.now(timezone.utc).isoformat(),
        })
        
        self._rebuild()
        self._save()
        return doc_id
    
    def add_many(self, items: List[Dict]) -> int:
        """Add multiple documents at once."""
        count = 0
        for item in items:
            doc_id = item.get("id", f"doc_{len(self.documents)}")
            self.documents.append({
                "id": doc_id,
                "text": item["text"],
                "metadata": item.get("metadata", {}),
                "added_at": datetime.now(timezone.utc).isoformat(),
            })
            count += 1
        
        self._rebuild()
        self._save()
        return count
    
    def search(self, query: str, limit: int = 5,
               min_score: float = 0.1) -> List[Dict]:
        """Semantic search."""
        if not self.documents:
            return []
        
        query_vec = self.vectorizer.transform(query)
        if not query_vec:
            return []
        
        scores = []
        for i, vec in enumerate(self._vectors):
            score = self.vectorizer.cosine_similarity(query_vec, vec)
            if score >= min_score:
                scores.append((score, i))
        
        scores.sort(reverse=True)
        
        results = []
        for score, idx in scores[:limit]:
            doc = self.documents[idx].copy()
            doc["score"] = round(score, 4)
            results.append(doc)
        
        return results
    
    def clear(self):
        self.documents = []
        self._vectors = []
        self._save()
    
    def stats(self) -> Dict:
        return {
            "name": self.name,
            "total_documents": len(self.documents),
            "vocab_size": len(self.vectorizer.vocab),
        }


# Global stores
code_store = VectorStore("code")
issues_store = VectorStore("issues")
learnings_store = VectorStore("learnings")

__all__ = ["VectorStore", "TFIDFVectorizer", "code_store", "issues_store", "learnings_store"]
