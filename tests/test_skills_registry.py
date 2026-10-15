"""Unit tests verifying the integrity, completeness, and schema validity of all skills."""

import unittest
from unittest.mock import MagicMock

from vyra import skills


class TestSkillsRegistry(unittest.TestCase):
    def test_total_skills_count(self):
        """Verify exactly 76 skills are registered across all modular categories."""
        self.assertEqual(len(skills.SKILLS), 76)
        self.assertIn("search_memory", skills._BY_NAME)

    def test_no_duplicate_skill_names(self):
        """Verify all skill names are globally unique."""
        names = [s["name"] for s in skills.SKILLS]
        self.assertEqual(len(names), len(set(names)), "Found duplicate skill names in registry")

    def test_skill_structure_and_schemas(self):
        """Verify every skill defines a callable fn, a description, and a valid parameters object."""
        for skill in skills.SKILLS:
            with self.subTest(skill=skill.get("name")):
                self.assertIn("name", skill)
                self.assertIn("fn", skill)
                self.assertIn("description", skill)
                self.assertIn("parameters", skill)

                self.assertTrue(callable(skill["fn"]), f"Skill {skill['name']} fn is not callable")
                self.assertIsInstance(skill["description"], str)
                self.assertTrue(len(skill["description"]) > 5)

                params = skill["parameters"]
                self.assertIsInstance(params, dict)
                self.assertEqual(params.get("type"), "object")
                self.assertIn("properties", params)
                self.assertIn("required", params)

    def test_tool_schemas_format_for_llm(self):
        """Verify tool_schemas() exports LLM-compatible JSON objects without internal fn pointers."""
        schemas = skills.tool_schemas()
        self.assertEqual(len(schemas), len(skills.SKILLS))
        for s in schemas:
            self.assertIn("name", s)
            self.assertIn("description", s)
            self.assertIn("parameters", s)
            self.assertNotIn("fn", s)  # Python function pointer must not be exposed to LLM

    def test_execute_unknown_skill(self):
        """Executing an unregistered skill must return a graceful error message without crashing."""
        mock_memory = MagicMock()
        res = skills.execute("non_existent_fake_skill", {}, mock_memory)
        self.assertIn("unknown skill", res)

    def test_execute_bad_arguments(self):
        """Passing incompatible arguments to a skill must return a bad argument error without crashing."""
        mock_memory = MagicMock()
        # open_app requires 'name'
        res = skills.execute("open_app", {"unrecognized_arg": 123}, mock_memory)
        self.assertIn("bad arguments", res)


if __name__ == "__main__":
    unittest.main()
