"""
GraphMemory - Connected knowledge network
- Nodes: lessons with auto-extracted concepts
- Edges: relations between lessons
- Smart retrieval: graph traversal, not just keyword match
"""
import json
import re
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List
from collections import defaultdict

from novamind.core.paths import NOVAMIND_HOME as BASE
GRAPH_FILE = BASE / "memory" / "knowledge_graph.json"

logger = logging.getLogger("graph_memory")


CONCEPT_KEYWORDS = {
    "division": ["divide", "division", "denominator", "zero"],
    "none_check": ["none", "null"],
    "type_check": ["type", "isinstance"],
    "bounds_check": ["index", "bounds", "range", "out of"],
    "key_access": ["key", "dict", "missing"],
    "file_io": ["file", "open", "read", "write"],
    "network": ["request", "http", "socket", "connect"],
    "async": ["async", "await", "coroutine"],
    "loop": ["for", "while", "iteration", "infinite"],
    "memory": ["memory", "leak", "allocation"],
    "exception": ["error", "exception", "try", "except", "raise"],
    "encoding": ["encode", "decode", "utf", "ascii"],
    "parsing": ["parse", "json", "xml", "yaml"],
    "threading": ["thread", "lock", "mutex", "race"],
    "validation": ["valid", "check", "verify", "assert"],
}


def extract_concepts(text):
    text_lower = text.lower()
    found = []
    for concept, keywords in CONCEPT_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                found.append(concept)
                break
    return found


def extract_keywords(text, max_kw=5):
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "can", "could", "should", "may", "might", "must", "shall",
        "and", "or", "but", "if", "then", "else", "when", "where",
        "which", "that", "this", "these", "those", "of", "in", "on",
        "at", "by", "for", "with", "without", "from", "to", "into",
    }
    words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b', text)
    meaningful = [w.lower() for w in words if w.lower() not in stop_words]
    seen = set()
    result = []
    for w in meaningful:
        if w not in seen:
            seen.add(w)
            result.append(w)
            if len(result) >= max_kw:
                break
    return result


class GraphMemory:
    def __init__(self, path=GRAPH_FILE):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self):
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("failed to load graph: " + str(e))
        return {
            "nodes": {},
            "edges": [],
            "concept_index": {},
            "keyword_index": {},
            "next_id": 1,
        }

    def _save(self):
        try:
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error("failed to save graph: " + str(e))

    def _index_concept(self, concept, node_id):
        idx = self.data["concept_index"]
        if concept not in idx:
            idx[concept] = []
        if node_id not in idx[concept]:
            idx[concept].append(node_id)

    def _index_keyword(self, keyword, node_id):
        idx = self.data["keyword_index"]
        if keyword not in idx:
            idx[keyword] = []
        if node_id not in idx[keyword]:
            idx[keyword].append(node_id)

    def add_lesson(self, text, source="", confidence=0.8):
        text = text.strip()
        if not text:
            return ""

        for node_id, node in self.data["nodes"].items():
            if node.get("text", "").lower() == text.lower():
                return node_id

        node_id = "L" + str(self.data["next_id"])
        self.data["next_id"] += 1

        concepts = extract_concepts(text)
        keywords = extract_keywords(text)

        node = {
            "id": node_id,
            "type": "lesson",
            "text": text,
            "source": source,
            "confidence": confidence,
            "concepts": concepts,
            "keywords": keywords,
            "created": datetime.now(timezone.utc).isoformat(),
        }

        self.data["nodes"][node_id] = node

        for c in concepts:
            self._index_concept(c, node_id)
        for kw in keywords:
            self._index_keyword(kw, node_id)

        for concept in concepts:
            for other_id in self.data["concept_index"].get(concept, []):
                if other_id != node_id:
                    self._add_edge(node_id, other_id,
                                   "shares_concept:" + concept, 0.5)

        self._save()
        logger.info("added lesson " + node_id +
                    " (concepts: " + str(concepts) + ")")
        return node_id

    def _add_edge(self, from_id, to_id, edge_type, weight=1.0):
        for edge in self.data["edges"]:
            if (edge["from"] == from_id and edge["to"] == to_id
                    and edge["type"] == edge_type):
                return
        self.data["edges"].append({
            "from": from_id,
            "to": to_id,
            "type": edge_type,
            "weight": weight,
        })

    def recall(self, query, limit=5):
        query = query.strip()
        if not query:
            return []

        query_lower = query.lower()
        query_concepts = extract_concepts(query)
        query_keywords = extract_keywords(query)

        scores = defaultdict(float)

        for kw in query_keywords:
            for node_id in self.data["keyword_index"].get(kw, []):
                scores[node_id] += 3.0

        for c in query_concepts:
            for node_id in self.data["concept_index"].get(c, []):
                scores[node_id] += 5.0

        for node_id, node in self.data["nodes"].items():
            if query_lower in node.get("text", "").lower():
                scores[node_id] += 2.0

        initial_ids = list(scores.keys())
        for edge in self.data["edges"]:
            if edge["from"] in initial_ids:
                scores[edge["to"]] += edge["weight"] * 0.5
            if edge["to"] in initial_ids:
                scores[edge["from"]] += edge["weight"] * 0.5

        ranked = sorted(scores.items(), key=lambda x: -x[1])[:limit]

        results = []
        for node_id, score in ranked:
            node = self.data["nodes"].get(node_id)
            if node:
                results.append({
                    "id": node_id,
                    "text": node["text"],
                    "score": round(score, 2),
                    "concepts": node.get("concepts", []),
                    "source": node.get("source", ""),
                })
        return results

    def stats(self):
        return {
            "total_nodes": len(self.data["nodes"]),
            "total_edges": len(self.data["edges"]),
            "total_concepts": len(self.data["concept_index"]),
            "total_keywords": len(self.data["keyword_index"]),
            "top_concepts": sorted(
                [(c, len(ids))
                 for c, ids in self.data["concept_index"].items()],
                key=lambda x: -x[1]
            )[:10],
        }

    def clear(self):
        self.data = {
            "nodes": {}, "edges": [], "concept_index": {},
            "keyword_index": {}, "next_id": 1,
        }
        self._save()


graph_memory = GraphMemory()
