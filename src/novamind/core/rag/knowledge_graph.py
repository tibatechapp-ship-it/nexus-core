"""
Knowledge Graph — Stores relationships between code entities.
Uses pure Python (no networkx required).
"""
import json
import logging
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Optional
from datetime import datetime, timezone

logger = logging.getLogger("core.rag.knowledge_graph")

from novamind.core.paths import NOVAMIND_HOME as BASE
KG_DIR = BASE / "memory" / "knowledge_graph"
KG_DIR.mkdir(parents=True, exist_ok=True)


class KnowledgeGraph:
    """
    Simple directed graph for code knowledge.
    Nodes: files, functions, classes, issues, patterns
    Edges: imports, calls, defines, has_issue
    """
    
    def __init__(self, name: str = "default"):
        self.name = name
        self.file = KG_DIR / f"{name}.json"
        
        # Adjacency list: node_id -> {edge_type: [target_ids]}
        self.nodes: Dict[str, Dict] = {}
        self.edges: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
        
        self._load()
    
    def _load(self):
        if self.file.exists():
            try:
                data = json.loads(self.file.read_text(encoding="utf-8"))
                self.nodes = data.get("nodes", {})
                edges_raw = data.get("edges", {})
                for src, targets in edges_raw.items():
                    for etype, tlist in targets.items():
                        self.edges[src][etype] = tlist
            except Exception as e:
                logger.warning(f"load failed: {e}")
    
    def _save(self):
        try:
            self.file.write_text(
                json.dumps({
                    "nodes": self.nodes,
                    "edges": dict(self.edges),
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"save failed: {e}")
    
    def add_node(self, node_id: str, node_type: str = "generic",
                 properties: Optional[Dict] = None):
        """Add or update a node."""
        if node_id not in self.nodes:
            self.nodes[node_id] = {
                "id": node_id,
                "type": node_type,
                "properties": properties or {},
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        else:
            # Merge properties
            if properties:
                self.nodes[node_id]["properties"].update(properties)
        
        self._save()
    
    def add_edge(self, from_node: str, to_node: str, edge_type: str = "related"):
        """Add a directed edge."""
        # Ensure nodes exist
        if from_node not in self.nodes:
            self.add_node(from_node, "unknown")
        if to_node not in self.nodes:
            self.add_node(to_node, "unknown")
        
        if to_node not in self.edges[from_node][edge_type]:
            self.edges[from_node][edge_type].append(to_node)
        
        self._save()
    
    def get_neighbors(self, node_id: str, edge_type: Optional[str] = None) -> List[str]:
        """Get neighbors of a node."""
        if node_id not in self.edges:
            return []
        
        if edge_type:
            return self.edges[node_id].get(edge_type, [])
        
        # All neighbors
        result = []
        for targets in self.edges[node_id].values():
            result.extend(targets)
        return result
    
    def find_path(self, start: str, end: str, max_depth: int = 5) -> Optional[List[str]]:
        """BFS path finding."""
        if start == end:
            return [start]
        
        visited = {start}
        queue = [(start, [start])]
        
        while queue:
            node, path = queue.pop(0)
            if len(path) > max_depth:
                continue
            
            for neighbor in self.get_neighbors(node):
                if neighbor == end:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))
        
        return None
    
    def subgraph(self, node_id: str, depth: int = 2) -> Dict:
        """Extract subgraph around a node."""
        nodes_set = set()
        edges_list = []
        
        def visit(nid, d):
            if d > depth or nid in nodes_set:
                return
            nodes_set.add(nid)
            for etype, targets in self.edges.get(nid, {}).items():
                for t in targets:
                    edges_list.append((nid, t, etype))
                    visit(t, d + 1)
        
        visit(node_id, 0)
        
        return {
            "nodes": [self.nodes.get(n, {"id": n}) for n in nodes_set],
            "edges": [{"from": e[0], "to": e[1], "type": e[2]} for e in edges_list],
        }
    
    def query(self, node_type: Optional[str] = None,
              property_filter: Optional[Dict] = None) -> List[Dict]:
        """Query nodes by type or properties."""
        results = []
        for node in self.nodes.values():
            if node_type and node.get("type") != node_type:
                continue
            if property_filter:
                props = node.get("properties", {})
                if not all(props.get(k) == v for k, v in property_filter.items()):
                    continue
            results.append(node)
        return results
    
    def stats(self) -> Dict:
        node_types = defaultdict(int)
        for n in self.nodes.values():
            node_types[n.get("type", "unknown")] += 1
        
        edge_types = defaultdict(int)
        for src in self.edges.values():
            for etype, targets in src.items():
                edge_types[etype] += len(targets)
        
        return {
            "name": self.name,
            "total_nodes": len(self.nodes),
            "total_edges": sum(edge_types.values()),
            "node_types": dict(node_types),
            "edge_types": dict(edge_types),
        }
    
    def clear(self):
        self.nodes = {}
        self.edges = defaultdict(lambda: defaultdict(list))
        self._save()


# Global graph
code_graph = KnowledgeGraph("code")

__all__ = ["KnowledgeGraph", "code_graph"]
