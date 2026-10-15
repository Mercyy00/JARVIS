"""Unit tests for vyra.brain module using mocked LLM client."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from vyra.brain import Brain, build_system_prompt
from vyra.llm import LLMResponse
from vyra.memory import Memory


class TestBrain(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.memory = Memory(self.test_dir)
        self.config = {
            "assistant": {"name": "Rusty", "mode": "tactical"},
            "user": {"name": "Jay"},
            "llm": {"provider": "google", "model": "gemini-flash-lite-latest", "api_key": "test_key"}
        }

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_system_prompt_structure(self):
        """Verify build_system_prompt injects persona, mode, and user context."""
        prompt = build_system_prompt(self.memory, "Jay", "Rusty", mode="tactical")
        self.assertIn("Rusty", prompt)
        self.assertIn("Jay", prompt)
        self.assertIn("TACTICAL", prompt)

        engineer_prompt = build_system_prompt(self.memory, "Jay", "Rusty", mode="engineer")
        self.assertIn("ENGINEER", engineer_prompt)

    @patch("vyra.brain.make_client")
    def test_brain_direct_text_reply(self, mock_make_client):
        """Verify Brain processes a direct textual reply from the LLM without tool calls."""
        mock_client = MagicMock()
        mock_client.complete.return_value = LLMResponse(
            text="Right away, Sir. Everything is functioning at peak efficiency.",
            tool_calls=[]
        )
        mock_make_client.return_value = mock_client

        brain = Brain(self.config, self.memory)
        reply = brain.ask("How are systems performing?")

        self.assertIn("Right away, Sir", reply)
        self.assertEqual(len(brain.history), 2)  # 1 user + 1 assistant
        self.assertEqual(brain.history[0]["content"], "How are systems performing?")

    @patch("vyra.brain.make_client")
    def test_fresh_start_clears_history(self, mock_make_client):
        """Verify fresh start phrases wipe the active conversation."""
        mock_client = MagicMock()
        mock_make_client.return_value = mock_client

        brain = Brain(self.config, self.memory)
        brain.history = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
        self.assertEqual(len(brain.history), 2)

        reply = brain.ask("start a fresh conversation")
        self.assertIn("Fresh start", reply)
        self.assertEqual(len(brain.history), 0)

    @patch("vyra.brain.make_client")
    def test_brain_tool_call_execution(self, mock_make_client):
        """Verify Brain handles a tool call step and queries LLM for final answer."""
        mock_client = MagicMock()
        # Turn 1: LLM decides to call 'get_datetime' tool
        call_turn = LLMResponse(
            text="",
            tool_calls=[{"id": "call_1", "name": "get_datetime", "args": {}}]
        )
        # Turn 2: LLM receives tool output and responds with final text
        final_turn = LLMResponse(
            text="It is currently Monday afternoon, Sir.",
            tool_calls=[]
        )
        mock_client.complete.side_effect = [call_turn, final_turn]
        mock_make_client.return_value = mock_client

        brain = Brain(self.config, self.memory)
        reply = brain.ask("What day is it today?")

        self.assertIn("Monday afternoon", reply)
        self.assertEqual(mock_client.complete.call_count, 2)


if __name__ == "__main__":
    unittest.main()
