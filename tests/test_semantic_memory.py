"""Unit tests verifying semantic memory recall, vector embeddings, JSON migration, and memory search skill."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from vyra import skills
from vyra.embeddings import (
    EMBEDDING_DIM,
    blob_to_vector,
    cosine_similarity,
    local_deterministic_embedding,
    vector_to_blob,
)
from vyra.memory import Memory


class TestEmbeddings(unittest.TestCase):
    def test_vector_serialization_roundtrip(self):
        """Vector to blob serialization and deserialization should preserve exact values."""
        vec = np.random.randn(EMBEDDING_DIM).astype(np.float32)
        blob = vector_to_blob(vec)
        self.assertIsInstance(blob, bytes)

        recovered = blob_to_vector(blob)
        self.assertEqual(recovered.shape, (EMBEDDING_DIM,))
        np.testing.assert_allclose(vec, recovered, rtol=1e-5)

    def test_cosine_similarity_properties(self):
        """Cosine similarity must be 1.0 for identical vectors, 0.0 for orthogonal."""
        v1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        v2 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        v3 = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        v_zero = np.array([0.0, 0.0, 0.0], dtype=np.float32)

        self.assertAlmostEqual(cosine_similarity(v1, v2), 1.0, places=5)
        self.assertAlmostEqual(cosine_similarity(v1, v3), 0.0, places=5)
        self.assertEqual(cosine_similarity(v1, v_zero), 0.0)

    def test_local_deterministic_embedding(self):
        """Deterministic vectorizer must produce 384-dim normalized, reproducible vectors."""
        text = "Autonomous assistant for hardware and software engineering"
        v1 = local_deterministic_embedding(text)
        v2 = local_deterministic_embedding(text)

        self.assertEqual(v1.shape, (EMBEDDING_DIM,))
        self.assertAlmostEqual(float(np.linalg.norm(v1)), 1.0, places=4)
        np.testing.assert_array_equal(v1, v2)

        # Semantically related text should have higher similarity than completely unrelated
        v_related = local_deterministic_embedding("Autonomous AI software agent")
        v_unrelated = local_deterministic_embedding("Strawberry cheesecake recipe baking ingredients")

        sim_related = cosine_similarity(v1, v_related)
        sim_unrelated = cosine_similarity(v1, v_unrelated)
        self.assertGreater(sim_related, sim_unrelated)


class TestSemanticMemory(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.mem = None

    def tearDown(self):
        if getattr(self, "mem", None):
            self.mem.close()
            self.mem = None
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def test_migration_from_existing_json_files(self):
        """Pre-existing JSON memory files must be seamlessly migrated to SQLite on first boot."""
        data_dir = self.root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        profile_json = {
            "name": "Mercy",
            "about": ["Mercy is an AI engineer", "Mercy prefers concise technical answers"],
            "preferences": ["Use dark theme"]
        }
        notes_json = [
            {"text": "Review GitHub pull requests tomorrow morning", "ts": "2026-10-15T10:00:00"}
        ]
        links_json = {
            "github": "https://github.com/Mercyy00/Rusty"
        }

        (data_dir / "profile.json").write_text(json.dumps(profile_json), encoding="utf-8")
        (data_dir / "notes.json").write_text(json.dumps(notes_json), encoding="utf-8")
        (data_dir / "links.json").write_text(json.dumps(links_json), encoding="utf-8")

        # Initialize Memory
        self.mem = Memory(self.root)

        # Verify SQLite DB has the migrated items
        db_facts = self.mem.db.list_facts()
        self.assertEqual(len(db_facts), 3)
        self.assertIn("Mercy is an AI engineer", db_facts)

        db_notes = self.mem.db.list_notes()
        self.assertEqual(len(db_notes), 1)
        self.assertIn("Review GitHub pull requests", db_notes[0]["text"])

        db_links = self.mem.db.list_links()
        self.assertEqual(db_links.get("github"), "https://github.com/Mercyy00/Rusty")

        self.assertEqual(self.mem.db.get_profile_value("name"), "Mercy")

    def test_semantic_search_and_context_injection(self):
        """Memories should be searchable and formatted into dynamic prompt context."""
        self.mem = Memory(self.root)
        self.mem.add_about("Mercy is building Rusty, a multi-modal desktop assistant in Python")
        self.mem.add_note("Project deadline for v2 is by Friday afternoon")

        # Semantic search
        results = self.mem.semantic_search("desktop assistant Python", top_k=3)
        self.assertTrue(len(results) > 0)
        top = results[0]
        self.assertIn("Rusty", top["content"])
        self.assertTrue(top["score"] > 0)

        # Prompt context generation
        ctx = self.mem.get_relevant_context("What is Rusty?")
        self.assertIn("RELEVANT RECALLED MEMORIES", ctx)
        self.assertIn("Rusty", ctx)

        # Short/blank query returns empty string
        self.assertEqual(self.mem.get_relevant_context("hi"), "")

    def test_search_memory_skill(self):
        """The search_memory skill should format recalled items cleanly for assistant output."""
        self.mem = Memory(self.root)
        self.mem.add_about("Mercy uses Neovim and VSCode for development")

        output = skills.execute("search_memory", {"query": "what editor does Mercy use?"}, self.mem)
        self.assertIn("Recalled memories for", output)
        self.assertIn("Neovim", output)

        # Non-matching query returns graceful message
        output_empty = skills.execute("search_memory", {"query": "xyz123randomnonexistent"}, self.mem)
        # Should either say no memories found or low relevance
        self.assertIsInstance(output_empty, str)


if __name__ == "__main__":
    unittest.main()
