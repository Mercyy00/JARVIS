"""Persistent Hybrid Memory Engine for Rusty.

Combines SQLite3, FTS5 full-text indexing, vector similarity retrieval,
and JSON/Markdown persistence for backward-compatible three-tier memory.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .database import MemoryDB
from .embeddings import get_embedding


class Memory:
    def __init__(self, root: Path, config: dict = None):
        self.root = Path(root)
        self.config = config or {}
        self.dir = self.root / "data"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.journal_dir = self.dir / "journal"
        self.journal_dir.mkdir(parents=True, exist_ok=True)

        self.profile_path = self.dir / "profile.json"
        self.links_path = self.dir / "links.json"
        self.notes_path = self.dir / "notes.json"

        # Initialize embedded SQLite database
        self.db = MemoryDB(self.dir / "rusty_memory.db")

        # Load file-based data
        self.profile = self._load(self.profile_path, {"name": None, "about": [], "preferences": []})
        self.links = self._load(self.links_path, {})
        self.notes = self._load(self.notes_path, [])

        # Run automated migration from JSON to SQLite if database is fresh
        self._migrate_json_to_sqlite()

    # --- low-level file I/O ---
    @staticmethod
    def _load(path: Path, default):
        if path.exists():
            try:
                return json.loads(path.read_text("utf-8"))
            except json.JSONDecodeError:
                return default
        return default

    @staticmethod
    def _save(path: Path, data):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
        try:
            tmp.replace(path)
        except Exception:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
            if tmp.exists():
                try:
                    tmp.unlink()
                except Exception:
                    pass

    def _migrate_json_to_sqlite(self):
        """Seed SQLite database with existing JSON memory on first run."""
        try:
            db_facts = self.db.list_facts()
            if not db_facts and (self.profile.get("about") or self.profile.get("preferences")):
                for fact in self.profile.get("about", []):
                    vec = get_embedding(fact, self.config)
                    self.db.add_fact(fact, category="about", vector=vec)
                for pref in self.profile.get("preferences", []):
                    vec = get_embedding(pref, self.config)
                    self.db.add_fact(pref, category="preference", vector=vec)

            db_notes = self.db.list_notes()
            if not db_notes and self.notes:
                for n in self.notes:
                    txt = n.get("text", "")
                    if txt:
                        vec = get_embedding(txt, self.config)
                        self.db.add_note(txt, vector=vec)

            db_links = self.db.list_links()
            if not db_links and self.links:
                for k, v in self.links.items():
                    self.db.save_link(k, v)

            if self.profile.get("name"):
                self.db.set_profile_value("name", self.profile["name"])
        except Exception as exc:
            print(f"[MEMORY] Notice: Non-fatal migration check: {exc}")

    # --- profile ---
    def set_name(self, name: str):
        self.profile["name"] = name
        self._save(self.profile_path, self.profile)
        self.db.set_profile_value("name", name)

    def add_about(self, fact: str):
        clean = fact.strip().lstrip("-* ").strip()
        if not clean:
            return
        about = self.profile.setdefault("about", [])
        clean_lower = clean.lower()
        if any(existing.lower() == clean_lower for existing in about):
            return
        about.append(clean)
        self._save(self.profile_path, self.profile)

        # Index in SQLite + Embeddings
        vec = get_embedding(clean, self.config)
        self.db.add_fact(clean, category="about", vector=vec)

    def delete_about(self, target: str) -> bool:
        target_clean = target.strip().lower()
        about = self.profile.get("about", [])
        initial_len = len(about)
        self.profile["about"] = [f for f in about if target_clean not in f.lower()]
        changed = len(self.profile["about"]) < initial_len
        if changed:
            self._save(self.profile_path, self.profile)
            self.db.delete_fact(target)
            return True
        return False

    def add_preference(self, pref: str):
        clean = pref.strip().lstrip("-* ").strip()
        if not clean:
            return
        prefs = self.profile.setdefault("preferences", [])
        clean_lower = clean.lower()
        if any(existing.lower() == clean_lower for existing in prefs):
            return
        prefs.append(clean)
        self._save(self.profile_path, self.profile)

        vec = get_embedding(clean, self.config)
        self.db.add_fact(clean, category="preference", vector=vec)

    def profile_text(self) -> str:
        p = self.profile
        lines = []
        if p.get("name"):
            lines.append(f"Name: {p['name']}")
        if p.get("about"):
            lines.append("About them:\n" + "\n".join(f"  - {x}" for x in p["about"]))
        if p.get("preferences"):
            lines.append("Preferences:\n" + "\n".join(f"  - {x}" for x in p["preferences"]))
        return "\n".join(lines) if lines else "(nothing saved yet)"

    # --- links ---
    def save_link(self, name: str, url: str):
        clean_name = name.lower().strip()
        self.links[clean_name] = url
        self._save(self.links_path, self.links)
        self.db.save_link(clean_name, url)

    def delete_link(self, name: str) -> bool:
        key = name.lower().strip()
        if key in self.links:
            del self.links[key]
            self._save(self.links_path, self.links)
            self.db.delete_link(key)
            return True
        return False

    def get_link(self, name: str):
        return self.links.get(name.lower().strip()) or self.db.get_link(name)

    def list_links(self) -> dict:
        return dict(self.links)

    # --- notes ---
    def add_note(self, text: str, tags: list[str] = None):
        clean = text.strip()
        self.notes.append({"text": clean, "ts": datetime.now().isoformat(timespec="seconds")})
        self._save(self.notes_path, self.notes)

        # Index in SQLite + Embeddings
        vec = get_embedding(clean, self.config)
        self.db.add_note(clean, tags=tags, vector=vec)

    def delete_note(self, query: str) -> bool:
        q = query.strip().lower()
        initial_len = len(self.notes)
        self.notes = [n for n in self.notes if q not in n.get("text", "").lower()]
        if len(self.notes) < initial_len:
            self._save(self.notes_path, self.notes)
            self.db.delete_note(query)
            return True
        return False

    def list_notes(self) -> list:
        return list(self.notes)

    # --- journal ---
    def _journal_path(self, day: date) -> Path:
        return self.journal_dir / f"{day.isoformat()}.md"

    def append_journal(self, text: str):
        path = self._journal_path(date.today())
        stamp = datetime.now().strftime("%H:%M")
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n- [{stamp}] {text}\n")
        # Also index journal entries into memory vectors
        vec = get_embedding(text, self.config)
        self.db.index_memory_item("journal", int(datetime.now().timestamp()), text, vector=vec)

    def recent_journal(self) -> str:
        chunks = []
        for day in (date.today() - timedelta(days=1), date.today()):
            path = self._journal_path(day)
            if path.exists():
                label = "Yesterday" if day != date.today() else "Today"
                chunks.append(f"## {label} ({day.isoformat()})\n{path.read_text('utf-8').strip()}")
        return "\n\n".join(chunks) if chunks else "(no recent history)"

    # --- Semantic Search & Dynamic Context Retrieval ---
    def semantic_search(self, query: str, top_k: int = 5, source_type: str = None) -> list[dict]:
        """Perform hybrid lexical and vector search across all memory stores."""
        query_vec = get_embedding(query, self.config)
        return self.db.hybrid_search(query, query_vec=query_vec, top_k=top_k, source_type=source_type)

    def get_relevant_context(self, query: str, max_items: int = 3) -> str:
        """Retrieve most relevant memories, notes, and facts formatted for LLM context injection."""
        if not query or len(query.strip()) < 4:
            return ""
        matches = self.semantic_search(query, top_k=max_items)
        if not matches:
            return ""

        context_lines = []
        for m in matches:
            if m["score"] > 0.12:  # Quality threshold
                src = m["source_type"].upper()
                snippet = m["content"].replace("\n", " ").strip()
                context_lines.append(f"- [{src}] {snippet}")

        if not context_lines:
            return ""
        return "== RELEVANT RECALLED MEMORIES ==\n" + "\n".join(context_lines)

    # --- Action and Turn Logging ---
    def log_turn(self, session_id: str, role: str, content: str, tool_calls: list = None):
        vec = get_embedding(content, self.config) if len(content) > 10 else None
        self.db.log_conversation_turn(session_id, role, content, tool_calls=tool_calls, vector=vec)

    def log_action(self, skill_name: str, args: dict, result: str, status: str = "success", duration_ms: float = 0.0):
        self.db.log_action(skill_name, args, result, status=status, duration_ms=duration_ms)

    def get_recent_actions(self, limit: int = 10) -> list[dict]:
        return self.db.get_recent_actions(limit=limit)

    def close(self):
        """Close backing SQLite database cleanly."""
        if hasattr(self, "db") and self.db is not None:
            self.db.close()

    def __del__(self):
        self.close()
