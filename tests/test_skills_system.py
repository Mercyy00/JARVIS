"""Unit tests for system and file skills execution."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from vyra.skills.common import _resolve_path, FOLDER_SHORTCUTS
from vyra.skills.system import (
    get_battery_status,
    get_system_info,
    switch_mode,
)
from vyra.skills.assistant import get_datetime
from vyra.skills.files import (
    list_folder,
    read_file,
    write_file,
)


class TestSkillsSystem(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.mock_memory = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_resolve_path_shortcuts(self):
        """Verify path shortcut resolution."""
        for shortcut, target in FOLDER_SHORTCUTS.items():
            expected = os.path.expandvars(target)
            resolved = _resolve_path(shortcut)
            self.assertEqual(resolved, expected)

        # Shortcut with subpath
        downloads_file = _resolve_path("downloads/test.txt")
        expected_dl = os.path.join(os.path.expandvars(r"%USERPROFILE%\Downloads"), "test.txt")
        self.assertEqual(downloads_file, expected_dl)

    def test_get_datetime(self):
        """Verify date and time string format."""
        dt_str = get_datetime(self.mock_memory)
        self.assertTrue(dt_str.startswith("It's "))
        self.assertIn(":", dt_str)

    def test_switch_mode_validation(self):
        """Verify mode validation and alias mapping."""
        # Valid modes
        self.assertIn("Tactical mode engaged", switch_mode(self.mock_memory, "tactical"))
        self.assertIn("Engineer mode engaged", switch_mode(self.mock_memory, "engineer"))
        self.assertIn("Ghost mode engaged", switch_mode(self.mock_memory, "ghost"))
        self.assertIn("Ghost mode engaged", switch_mode(self.mock_memory, "stealth"))  # Alias
        self.assertIn("Ghost mode engaged", switch_mode(self.mock_memory, "silent"))   # Alias

        # Invalid mode
        err = switch_mode(self.mock_memory, "ultra_god_mode")
        self.assertIn("Unknown mode", err)

    def test_get_system_info(self):
        """Verify hardware metrics reporting."""
        info = get_system_info(self.mock_memory)
        self.assertIn("CPU", info)
        self.assertIn("RAM", info)

    def test_get_battery_status(self):
        """Verify battery status returns a formatted string without throwing."""
        battery = get_battery_status(self.mock_memory)
        self.assertTrue("Battery" in battery or "AC power" in battery)

    def test_write_and_read_file(self):
        """Verify creating, writing, and reading a file."""
        target_path = os.path.join(self.test_dir, "notes.txt")
        content = "Line 1: Build AI assistant.\nLine 2: Test security boundaries."

        # Write file
        write_res = write_file(self.mock_memory, target_path, content)
        self.assertIn("Saved file", write_res)
        self.assertTrue(os.path.exists(target_path))

        # Read file
        read_res = read_file(self.mock_memory, target_path)
        self.assertIn("Contents of notes.txt", read_res)
        self.assertIn("Build AI assistant", read_res)

    def test_list_folder(self):
        """Verify folder listing with files and subdirectories."""
        os.makedirs(os.path.join(self.test_dir, "subdir"))
        with open(os.path.join(self.test_dir, "item1.txt"), "w") as f:
            f.write("Hello")

        res = list_folder(self.mock_memory, self.test_dir)
        self.assertIn("[DIR]  subdir", res)
        self.assertIn("[FILE] item1.txt", res)


if __name__ == "__main__":
    unittest.main()
