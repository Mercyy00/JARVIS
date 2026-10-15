"""Unit tests for SQLite MemoryDB, FTS5 full-text indexing, vector storage, and action logging."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from vyra.database import MemoryDB
from vyra.embeddings import (
    EMBEDDING_DIM,
    blob_to_vector,
    cosine_similarity,
    local_deterministic_embedding,
    vector_to_blob,
)


class TestMemoryDB(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_rusty.db"
        self.db = MemoryDB(self.db_path)

    def tearDown(self):
        if hasattr(self, "db") and self.db:
            self.db.close()
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def test_init_creates_all_tables_and_fts(self):
        """Verify that all core relational tables and FTS5 virtual tables are initialized."""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'shadow');")
            names = {row["name"] for row in cursor.fetchall()}

            expected_tables = {
                "user_profile",
                "facts",
                "notes",
                "links",
                "conversations",
                "action_logs",
                "memory_vectors",
                "memory_fts",
            }
            for tbl in expected_tables:
                self.assertIn(tbl, names, f"Expected table {tbl} was not created")

    def test_user_profile_operations(self):
        """Verify setting, retrieving, and overwriting profile attributes."""
        self.db.set_profile_value("name", "Jay")
        self.assertEqual(self.db.get_profile_value("name"), "Jay")

        # Complex dictionary / JSON storage
        pref = {"editor": "vscode", "theme": "dark"}
        self.db.set_profile_value("preferences", pref)
        self.assertEqual(self.db.get_profile_value("preferences"), pref)

        # Overwrite value
        self.db.set_profile_value("name", "Mercy")
        self.assertEqual(self.db.get_profile_value("name"), "Mercy")

        # Missing key returns default
        self.assertIsNone(self.db.get_profile_value("nonexistent"))
        self.assertEqual(self.db.get_profile_value("nonexistent", "fallback"), "fallback")

    def test_facts_crud_and_indexing(self):
        """Verify fact insertion, deduplication, listing, and deletion with vector/FTS cleanup."""
        fact_id = self.db.add_fact("Jay is building an autonomous AI system called Rusty")
        self.assertTrue(fact_id > 0)

        # Adding same fact again should not create duplicate
        dup_id = self.db.add_fact("Jay is building an autonomous AI system called Rusty")
        self.assertEqual(fact_id, dup_id)

        facts = self.db.list_facts()
        self.assertEqual(len(facts), 1)
        self.assertIn("Jay is building an autonomous AI system called Rusty", facts[0])

        # Delete fact
        deleted = self.db.delete_fact("autonomous AI system")
        self.assertTrue(deleted)
        self.assertEqual(len(self.db.list_facts()), 0)

        # Verify FTS and vector records were also deleted
        fts_res = self.db.fts_search("autonomous")
        self.assertEqual(len(fts_res), 0)

    def test_notes_operations(self):
        """Verify adding, listing, and deleting timestamped notes."""
        note_id1 = self.db.add_note("Buy groceries: milk, eggs, bread", tags=["shopping"])
        note_id2 = self.db.add_note("Inspect neural network loss curves", tags=["ml", "research"])
        self.assertTrue(note_id1 > 0)
        self.assertTrue(note_id2 > 0)

        notes = self.db.list_notes()
        self.assertEqual(len(notes), 2)
        self.assertIn("Buy groceries", notes[1]["text"])
        self.assertIn("shopping", notes[1]["tags"])

        # Delete note
        self.assertTrue(self.db.delete_note("groceries"))
        self.assertEqual(len(self.db.list_notes()), 1)
        self.assertFalse(self.db.delete_note("nonexistent"))

    def test_links_operations(self):
        """Verify saving, getting, listing, and deleting named URL bookmarks."""
        self.db.save_link("github", "https://github.com/Mercyy00/Rusty", "Project repo")
        self.assertEqual(self.db.get_link("github"), "https://github.com/Mercyy00/Rusty")
        self.assertEqual(self.db.get_link("GITHUB"), "https://github.com/Mercyy00/Rusty")

        links = self.db.list_links()
        self.assertIn("github", links)

        self.assertTrue(self.db.delete_link("github"))
        self.assertIsNone(self.db.get_link("github"))

    def test_conversation_logging(self):
        """Verify conversation turns logging and retrieval."""
        self.db.log_conversation_turn("session_1", "user", "What is the status of our project?")
        self.db.log_conversation_turn("session_1", "assistant", "All systems operational, Sir.")

        history = self.db.get_recent_conversation(limit=10)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[1]["role"], "assistant")
        self.assertIn("All systems operational", history[1]["content"])

    def test_action_logging(self):
        """Verify structured execution log captures tool invocations and timings."""
        self.db.log_action("run_terminal_command", {"command": "git status"}, "On branch main", status="success", duration_ms=12.5)
        self.db.log_action("open_app", {"name": "notepad"}, "Opened notepad", status="success", duration_ms=45.2)

        actions = self.db.get_recent_actions(limit=5)
        self.assertEqual(len(actions), 2)
        # Most recent first
        self.assertEqual(actions[0]["skill_name"], "open_app")
        self.assertEqual(actions[0]["duration_ms"], 45.2)
        self.assertEqual(actions[1]["skill_name"], "run_terminal_command")

    def test_fts5_lexical_search(self):
        """Verify full-text search retrieves items matching query tokens."""
        self.db.add_note("Configure Docker container for deployment", tags=["devops"])
        self.db.add_note("Implement vector database for semantic search", tags=["search"])
        self.db.add_fact("Mercy prefers dark mode in all editors")

        results = self.db.fts_search("Docker container")
        self.assertTrue(len(results) > 0)
        self.assertIn("Docker", results[0]["content"])
        self.assertEqual(results[0]["source_type"], "note")

        fact_results = self.db.fts_search("dark mode")
        self.assertTrue(len(fact_results) > 0)
        self.assertIn("dark mode", fact_results[0]["content"])
        self.assertEqual(fact_results[0]["source_type"], "fact")

    def test_vector_and_hybrid_search(self):
        """Verify dense vector similarity search and hybrid lexical+semantic ranking."""
        vec1 = local_deterministic_embedding("quantum computing algorithm")
        vec2 = local_deterministic_embedding("chocolate chip cookie recipe")
        vec3 = local_deterministic_embedding("quantum physics entanglement experiment")

        self.db.add_note("Researching quantum computing algorithms and Shor's algorithm", vector=vec1)
        self.db.add_note("Grandma's secret chocolate chip cookie recipe", vector=vec2)
        self.db.add_note("Laboratory test on quantum entanglement and qubits", vector=vec3)

        # Semantic vector search for "quantum algorithms"
        query_vec = local_deterministic_embedding("quantum physics research")
        vec_matches = self.db.vector_search(query_vec, limit=2)
        self.assertTrue(len(vec_matches) > 0)
        # Quantum notes should score much higher than cookie recipe
        top_content = vec_matches[0]["content"].lower()
        self.assertIn("quantum", top_content)

        # Hybrid search combines both
        hybrid_matches = self.db.hybrid_search("quantum physics", query_vec=query_vec, top_k=2)
        self.assertTrue(len(hybrid_matches) > 0)
        self.assertIn("quantum", hybrid_matches[0]["content"].lower())


if __name__ == "__main__":
    unittest.main()
