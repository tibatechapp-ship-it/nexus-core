"""Simple SQLite-based Knowledge Graph."""
from __future__ import annotations
import sqlite3
import json
from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class Entity:
    id: str
    type: str
    properties: dict = field(default_factory=dict)


@dataclass
class Relation:
    source: str
    target: str
    type: str
    properties: dict = field(default_factory=dict)


class KnowledgeGraph:
    """رسم بياني بسيط للمعرفة على SQLite."""

    def __init__(self: Any, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path)
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                properties TEXT
            );
            CREATE TABLE IF NOT EXISTS relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                type TEXT NOT NULL,
                properties TEXT,
                UNIQUE(source, target, type)
            );
            CREATE INDEX IF NOT EXISTS idx_rel_source ON relations(source);
            CREATE INDEX IF NOT EXISTS idx_rel_target ON relations(target);
        """)
        self._conn.commit()

    def add_entity(self, entity: Entity) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO entities(id, type, properties) VALUES (?, ?, ?)",
            (entity.id, entity.type, json.dumps(entity.properties)),
        )
        self._conn.commit()

    def add_relation(self, rel: Relation) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO relations(source, target, type, properties) "
            "VALUES (?, ?, ?, ?)",
            (rel.source, rel.target, rel.type, json.dumps(rel.properties)),
        )
        self._conn.commit()

    def neighbors(self, entity_id: str, depth: int = 1) -> list:
        """يُرجع الجيران حتى عمق معين (BFS يجمع كل عقدة مكتشفة)."""
        visited: set[str] = {entity_id}
        found: set[str] = set()
        frontier: set[str] = {entity_id}
        for _ in range(depth):
            next_frontier: set[str] = set()
            for node in frontier:
                rows = self._conn.execute(
                    "SELECT target FROM relations WHERE source = ? "
                    "UNION SELECT source FROM relations WHERE target = ?",
                    (node, node),
                ).fetchall()
                for row in rows:
                    neighbor = row[0]
                    if neighbor not in visited:
                        visited.add(neighbor)
                        found.add(neighbor)
                        next_frontier.add(neighbor)
            frontier = next_frontier
        return list(found)

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        row = self._conn.execute(
            "SELECT id, type, properties FROM entities WHERE id = ?",
            (entity_id,),
        ).fetchone()
        if not row:
            return None
        return Entity(
            id=row[0], type=row[1],
            properties=json.loads(row[2] or "{}"),
        )
