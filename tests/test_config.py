"""Tests for vyra.config module."""

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from vyra.config import _deep_merge, has_api_key, load_config, DEFAULTS


class TestConfig(unittest.TestCase):
    def test_defaults_structure(self):
        """Verify DEFAULTS contains all mandatory sections."""
        self.assertIn("assistant", DEFAULTS)
        self.assertIn("llm", DEFAULTS)
        self.assertIn("user", DEFAULTS)
        self.assertIn("voice", DEFAULTS)
        self.assertEqual(DEFAULTS["assistant"]["name"], "Rusty")

    def test_deep_merge(self):
        """Verify recursive dictionary merging."""
        base = {"a": 1, "b": {"c": 2, "d": 3}}
        override = {"b": {"d": 4, "e": 5}, "f": 6}
        merged = _deep_merge(base, override)
        self.assertEqual(merged["a"], 1)
        self.assertEqual(merged["b"]["c"], 2)
        self.assertEqual(merged["b"]["d"], 4)
        self.assertEqual(merged["b"]["e"], 5)
        self.assertEqual(merged["f"], 6)

    def test_has_api_key(self):
        """Verify API key presence checks."""
        self.assertFalse(has_api_key({"llm": {}}))
        self.assertFalse(has_api_key({"llm": {"api_key": ""}}))
        self.assertFalse(has_api_key({"llm": {"api_key": None}}))
        self.assertTrue(has_api_key({"llm": {"api_key": "valid_token_xyz"}}))

    def test_load_config_env_overrides(self):
        """Verify environment variables override config settings."""
        with patch.dict(os.environ, {
            "VYRA_PROVIDER": "openrouter",
            "VYRA_MODEL": "meta-llama/llama-3-70b-instruct",
            "VYRA_API_KEY": "sk-test-key-12345",
        }):
            cfg = load_config()
            self.assertEqual(cfg["llm"]["provider"], "openrouter")
            self.assertEqual(cfg["llm"]["model"], "meta-llama/llama-3-70b-instruct")
            self.assertEqual(cfg["llm"]["api_key"], "sk-test-key-12345")


if __name__ == "__main__":
    unittest.main()
