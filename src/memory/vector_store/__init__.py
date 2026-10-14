"""Vector Store — بحث دلالي عبر sqlite-vec.

يوفر واجهة موحدة لمخازن vectors، مع تنفيذ أساسي عبر sqlite-vec.
"""
from .base import VectorStore, SearchResult
from .sqlite_vec_store import SQLiteVecStore

__all__ = ["VectorStore", "SearchResult", "SQLiteVecStore"]
