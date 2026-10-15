"""Embedded SQLite database engine with FTS5 full-text indexing, vector storage, and action logging for Rusty."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .embeddings import (
    EMBEDDING_DIM,
    batch_cosine_similarity,
    blob_to_vector,
    vector_to_blob,
)


class MemoryDB:
    """Thread-safe SQLite storage engine with FTS5 and vector similarity search."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create or return the configured SQLite connection with row factories and WAL mode."""
        if self._conn is None:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=20.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            self._conn = conn
        return self._conn

    def close(self):
        """Cleanly close database connection and release file locks."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def __del__(self):
        self.close()

    def _init_db(self):
        """Create database tables and FTS5 search index."""
        with self._lock, self._get_connection() as conn:
            # 1. User profile key-value attributes
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_profile (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

            # 2. Long-term user facts and details
            conn.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT DEFAULT 'general',
                    content TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

            # 3. User notes with timestamp
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    tags TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

            # 4. Named URL links
            conn.execute("""
                CREATE TABLE IF NOT EXISTS links (
                    name TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    last_accessed TEXT NOT NULL
                );
            """)

            # 5. Full conversation history across sessions
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tool_calls TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL
                );
            """)

            # 6. Structured action and skill execution logs
            conn.execute("""
                CREATE TABLE IF NOT EXISTS action_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    skill_name TEXT NOT NULL,
                    args TEXT DEFAULT '{}',
                    result TEXT DEFAULT '',
                    status TEXT NOT NULL,
                    duration_ms REAL DEFAULT 0.0
                );
            """)

            # 7. Dense Vector Embeddings for semantic retrieval
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_vectors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_type TEXT NOT NULL,
                    source_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    dim INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(source_type, source_id)
                );
            """)

            # 8. FTS5 Virtual Table for full-text lexical search
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    content,
                    source_type,
                    source_id UNINDEXED,
                    tokenize='porter unicode61'
                );
            """)
            conn.commit()

    # --- Profile Operations ---
    def set_profile_value(self, key: str, value: Any):
        val_str = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        now = datetime.now().isoformat()
        with self._lock, self._get_connection() as conn:
            conn.execute(
                "INSERT INTO user_profile (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at;",
                (key, val_str, now)
            )
            conn.commit()

    def get_profile_value(self, key: str, default: Any = None) -> Any:
        with self._lock, self._get_connection() as conn:
            row = conn.execute("SELECT value FROM user_profile WHERE key = ?;", (key,)).fetchone()
            if not row:
                return default
            val = row["value"]
            try:
                return json.loads(val)
            except Exception:
                return val

    # --- Facts Operations ---
    def add_fact(self, content: str, category: str = "general", vector: np.ndarray = None) -> int:
        clean = content.strip().lstrip("-* ").strip()
        if not clean:
            return 0
        now = datetime.now().isoformat()
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT OR IGNORE INTO facts (category, content, created_at) VALUES (?, ?, ?);",
                (category, clean, now)
            )
            fact_id = cur.lastrowid
            if not fact_id:
                row = conn.execute("SELECT id FROM facts WHERE content = ?;", (clean,)).fetchone()
                fact_id = row["id"] if row else 0
            conn.commit()

        if fact_id:
            self.index_memory_item("fact", fact_id, clean, vector)
        return fact_id

    def list_facts(self) -> list[str]:
        with self._lock, self._get_connection() as conn:
            rows = conn.execute("SELECT content FROM facts ORDER BY id ASC;").fetchall()
            return [r["content"] for r in rows]

    def delete_fact(self, query: str) -> bool:
        q = query.strip().lower()
        with self._lock, self._get_connection() as conn:
            rows = conn.execute("SELECT id, content FROM facts;").fetchall()
            matching = [r for r in rows if q in r["content"].lower()]
            if not matching:
                return False
            for m in matching:
                conn.execute("DELETE FROM facts WHERE id = ?;", (m["id"],))
                conn.execute("DELETE FROM memory_vectors WHERE source_type='fact' AND source_id=?;", (m["id"],))
                conn.execute("DELETE FROM memory_fts WHERE source_type='fact' AND source_id=?;", (str(m["id"]),))
            conn.commit()
            return True

    # --- Notes Operations ---
    def add_note(self, text: str, tags: list[str] = None, vector: np.ndarray = None) -> int:
        now = datetime.now().isoformat()
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO notes (text, tags, created_at, updated_at) VALUES (?, ?, ?, ?);",
                (text.strip(), tags_json, now, now)
            )
            note_id = cur.lastrowid
            conn.commit()

        if note_id:
            self.index_memory_item("note", note_id, text, vector)
        return note_id

    def list_notes(self) -> list[dict]:
        with self._lock, self._get_connection() as conn:
            rows = conn.execute("SELECT id, text, tags, created_at FROM notes ORDER BY id DESC;").fetchall()
            return [
                {
                    "id": r["id"],
                    "text": r["text"],
                    "tags": json.loads(r["tags"] or "[]"),
                    "ts": r["created_at"],
                }
                for r in rows
            ]

    def delete_note(self, query: str) -> bool:
        q = query.strip().lower()
        with self._lock, self._get_connection() as conn:
            rows = conn.execute("SELECT id, text FROM notes;").fetchall()
            matching = [r for r in rows if q in r["text"].lower()]
            if not matching:
                return False
            for m in matching:
                conn.execute("DELETE FROM notes WHERE id = ?;", (m["id"],))
                conn.execute("DELETE FROM memory_vectors WHERE source_type='note' AND source_id=?;", (m["id"],))
                conn.execute("DELETE FROM memory_fts WHERE source_type='note' AND source_id=?;", (str(m["id"]),))
            conn.commit()
            return True

    # --- Links Operations ---
    def save_link(self, name: str, url: str, description: str = ""):
        clean_name = name.strip().lower()
        now = datetime.now().isoformat()
        with self._lock, self._get_connection() as conn:
            conn.execute(
                "INSERT INTO links (name, url, description, created_at, last_accessed) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET url=excluded.url, description=excluded.description, last_accessed=excluded.last_accessed;",
                (clean_name, url.strip(), description, now, now)
            )
            conn.commit()

    def get_link(self, name: str) -> Optional[str]:
        clean_name = name.strip().lower()
        with self._lock, self._get_connection() as conn:
            row = conn.execute("SELECT url FROM links WHERE name = ?;", (clean_name,)).fetchone()
            if row:
                now = datetime.now().isoformat()
                conn.execute("UPDATE links SET last_accessed = ? WHERE name = ?;", (now, clean_name))
                conn.commit()
                return row["url"]
            return None

    def list_links(self) -> dict[str, str]:
        with self._lock, self._get_connection() as conn:
            rows = conn.execute("SELECT name, url FROM links ORDER BY name ASC;").fetchall()
            return {r["name"]: r["url"] for r in rows}

    def delete_link(self, name: str) -> bool:
        clean_name = name.strip().lower()
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM links WHERE name = ?;", (clean_name,))
            conn.commit()
            return cur.rowcount > 0

    # --- Conversations Logging ---
    def log_conversation_turn(self, session_id: str, role: str, content: str, tool_calls: list = None, vector: np.ndarray = None) -> int:
        now = datetime.now().isoformat()
        tc_json = json.dumps(tool_calls or [], ensure_ascii=False)
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO conversations (session_id, role, content, tool_calls, created_at) "
                "VALUES (?, ?, ?, ?, ?);",
                (session_id, role, content, tc_json, now)
            )
            turn_id = cur.lastrowid
            conn.commit()

        # Index user and assistant turns for semantic retrieval
        if turn_id and len(content.strip()) > 10:
            self.index_memory_item("conversation", turn_id, content, vector)
        return turn_id

    def get_recent_conversation(self, limit: int = 40) -> list[dict]:
        with self._lock, self._get_connection() as conn:
            rows = conn.execute(
                "SELECT role, content, tool_calls, created_at FROM conversations "
                "ORDER BY id DESC LIMIT ?;", (limit,)
            ).fetchall()
            # Return in chronological order
            return [
                {
                    "role": r["role"],
                    "content": r["content"],
                    "tool_calls": json.loads(r["tool_calls"] or "[]"),
                    "created_at": r["created_at"],
                }
                for r in reversed(rows)
            ]

    # --- Structured Action Logging ---
    def log_action(self, skill_name: str, args: dict, result: str, status: str = "success", duration_ms: float = 0.0):
        now = datetime.now().isoformat()
        args_str = json.dumps(args or {}, ensure_ascii=False)
        result_preview = (result or "")[:500]
        with self._lock, self._get_connection() as conn:
            conn.execute(
                "INSERT INTO action_logs (timestamp, skill_name, args, result, status, duration_ms) "
                "VALUES (?, ?, ?, ?, ?, ?);",
                (now, skill_name, args_str, result_preview, status, duration_ms)
            )
            conn.commit()

    def get_recent_actions(self, limit: int = 15) -> list[dict]:
        with self._lock, self._get_connection() as conn:
            rows = conn.execute(
                "SELECT id, timestamp, skill_name, args, result, status, duration_ms "
                "FROM action_logs ORDER BY id DESC LIMIT ?;", (limit,)
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "timestamp": r["timestamp"],
                    "skill_name": r["skill_name"],
                    "args": json.loads(r["args"] or "{}"),
                    "result": r["result"],
                    "status": r["status"],
                    "duration_ms": r["duration_ms"],
                }
                for r in rows
            ]

    # --- Search & Semantic Vector Indexing ---
    def index_memory_item(self, source_type: str, source_id: int, content: str, vector: np.ndarray = None):
        """Index a text fragment into both FTS5 table and vector table."""
        if not content or not content.strip():
            return
        clean_text = content.strip()
        now = datetime.now().isoformat()

        if vector is None:
            from .embeddings import local_deterministic_embedding
            vector = local_deterministic_embedding(clean_text)

        blob = vector_to_blob(vector)
        dim = len(vector)

        with self._lock, self._get_connection() as conn:
            # 1. Update or Insert Vector
            conn.execute("""
                INSERT INTO memory_vectors (source_type, source_id, content, embedding, dim, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_type, source_id) DO UPDATE SET
                    content=excluded.content,
                    embedding=excluded.embedding,
                    dim=excluded.dim,
                    created_at=excluded.created_at;
            """, (source_type, source_id, clean_text, blob, dim, now))

            # 2. Update FTS index
            conn.execute("DELETE FROM memory_fts WHERE source_type = ? AND source_id = ?;", (source_type, str(source_id)))
            conn.execute(
                "INSERT INTO memory_fts (content, source_type, source_id) VALUES (?, ?, ?);",
                (clean_text, source_type, str(source_id))
            )
            conn.commit()

    def fts_search(self, query: str, limit: int = 10, source_type: str = None) -> list[dict]:
        """Lexical full-text search via SQLite FTS5."""
        clean_q = re.sub(r"[^\w\s]", " ", query).strip()
        if not clean_q:
            return []
        # Format query for FTS5 (e.g. "robotics* OR project*")
        terms = [f"{t}*" for t in clean_q.split() if len(t) > 1]
        if not terms:
            return []
        match_expr = " OR ".join(terms)

        with self._lock, self._get_connection() as conn:
            if source_type:
                sql = """
                    SELECT source_type, source_id, content, rank
                    FROM memory_fts
                    WHERE memory_fts MATCH ? AND source_type = ?
                    ORDER BY rank LIMIT ?;
                """
                rows = conn.execute(sql, (match_expr, source_type, limit)).fetchall()
            else:
                sql = """
                    SELECT source_type, source_id, content, rank
                    FROM memory_fts
                    WHERE memory_fts MATCH ?
                    ORDER BY rank LIMIT ?;
                """
                rows = conn.execute(sql, (match_expr, limit)).fetchall()

            results = []
            for r in rows:
                # SQLite FTS5 bm25 rank is negative (lower = more relevant)
                score = max(0.0, 1.0 / (1.0 + abs(r["rank"])))
                results.append({
                    "source_type": r["source_type"],
                    "source_id": int(r["source_id"]),
                    "content": r["content"],
                    "score": float(score),
                    "match_type": "lexical"
                })
            return results

    def vector_search(self, query_vec: np.ndarray, limit: int = 10, source_type: str = None) -> list[dict]:
        """Dense vector search using cosine similarity across indexed embeddings."""
        if query_vec is None or np.all(query_vec == 0):
            return []

        with self._lock, self._get_connection() as conn:
            if source_type:
                sql = "SELECT source_type, source_id, content, embedding FROM memory_vectors WHERE source_type = ?;"
                rows = conn.execute(sql, (source_type,)).fetchall()
            else:
                sql = "SELECT source_type, source_id, content, embedding FROM memory_vectors;"
                rows = conn.execute(sql).fetchall()

            if not rows:
                return []

            doc_vectors = np.array([blob_to_vector(r["embedding"]) for r in rows], dtype=np.float32)
            similarities = batch_cosine_similarity(query_vec, doc_vectors)

            # Sort descending by similarity
            top_indices = np.argsort(similarities)[::-1][:limit]
            results = []
            for idx in top_indices:
                score = float(similarities[idx])
                if score > 0.05:  # Relevance threshold
                    r = rows[idx]
                    results.append({
                        "source_type": r["source_type"],
                        "source_id": int(r["source_id"]),
                        "content": r["content"],
                        "score": score,
                        "match_type": "semantic"
                    })
            return results

    def hybrid_search(self, query: str, query_vec: np.ndarray = None, top_k: int = 5, source_type: str = None, alpha: float = 0.5) -> list[dict]:
        """Hybrid search combining BM25 lexical ranking and dense vector similarity."""
        if query_vec is None:
            from .embeddings import local_deterministic_embedding
            query_vec = local_deterministic_embedding(query)

        fts_res = self.fts_search(query, limit=top_k * 2, source_type=source_type)
        vec_res = self.vector_search(query_vec, limit=top_k * 2, source_type=source_type)

        combined: dict[tuple[str, int], dict] = {}

        # Add FTS scores
        for item in fts_res:
            key = (item["source_type"], item["source_id"])
            combined[key] = {
                "source_type": item["source_type"],
                "source_id": item["source_id"],
                "content": item["content"],
                "score": (1.0 - alpha) * item["score"],
                "match_type": "lexical"
            }

        # Merge Vector scores
        for item in vec_res:
            key = (item["source_type"], item["source_id"])
            if key in combined:
                combined[key]["score"] += alpha * item["score"]
                combined[key]["match_type"] = "hybrid"
            else:
                combined[key] = {
                    "source_type": item["source_type"],
                    "source_id": item["source_id"],
                    "content": item["content"],
                    "score": alpha * item["score"],
                    "match_type": "semantic"
                }

        sorted_items = sorted(combined.values(), key=lambda x: x["score"], reverse=True)
        return sorted_items[:top_k]
