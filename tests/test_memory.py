"""Unit tests for vyra.memory module."""

import shutil
import tempfile
import unittest
from pathlib import Path

from vyra.memory import Memory


class TestMemory(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.memory = Memory(self.test_dir)

    def tearDown(self):
        if hasattr(self, "memory") and self.memory:
            self.memory.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_profile_name(self):
        """Verify setting and reading user name."""
        self.memory.set_name("Jay")
        self.assertEqual(self.memory.profile["name"], "Jay")
        self.assertIn("Name: Jay", self.memory.profile_text())

    def test_facts_about_user(self):
        """Verify adding, deduplicating, and deleting facts."""
        self.memory.add_about("Loves robotics and AI")
        self.memory.add_about("loves robotics and ai")  # Case-insensitive duplicate
        self.assertEqual(len(self.memory.profile["about"]), 1)

        self.memory.add_about("Studies software engineering")
        self.assertEqual(len(self.memory.profile["about"]), 2)

        # Delete fact
        deleted = self.memory.delete_about("robotics")
        self.assertTrue(deleted)
        self.assertEqual(len(self.memory.profile["about"]), 1)
        self.assertNotIn("robotics", self.memory.profile_text().lower())

    def test_saved_links(self):
        """Verify saving, retrieving, listing, and deleting links."""
        self.memory.save_link("Daily Standup", "https://meet.google.com/abc-defg-hij")
        self.assertEqual(self.memory.get_link("daily standup"), "https://meet.google.com/abc-defg-hij")

        links = self.memory.list_links()
        self.assertIn("daily standup", links)

        deleted = self.memory.delete_link("daily standup")
        self.assertTrue(deleted)
        self.assertIsNone(self.memory.get_link("daily standup"))

    def test_notes(self):
        """Verify adding, searching, and deleting notes."""
        self.memory.add_note("Buy solder wire for drone project")
        self.memory.add_note("Review PR on GitHub")
        self.assertEqual(len(self.memory.list_notes()), 2)

        deleted = self.memory.delete_note("solder wire")
        self.assertTrue(deleted)
        self.assertEqual(len(self.memory.list_notes()), 1)
        self.assertIn("Review PR", self.memory.list_notes()[0]["text"])

    def test_journal(self):
        """Verify appending and reading journal entries."""
        self.memory.append_journal("Completed security audit of Rusty assistant")
        journal = self.memory.recent_journal()
        self.assertIn("Completed security audit", journal)


if __name__ == "__main__":
    unittest.main()
