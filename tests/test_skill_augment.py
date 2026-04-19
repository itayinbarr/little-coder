"""Tests for local/skill_augment.py — skill loading, selection, injection."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from local.skill_augment import (
    load_tool_skills, select_and_inject_skills, clear_cache,
    _find_last_failed_tool, _get_recent_tools, _predict_tools,
)


class TestToolSkillLoading(unittest.TestCase):

    def test_loads_skill_files(self):
        skills = load_tool_skills()
        self.assertGreater(len(skills), 0)
        # Should have at least Read, Write, Edit, Bash
        self.assertIn("Read", skills)
        self.assertIn("Edit", skills)
        self.assertIn("Bash", skills)

    def test_skill_has_prompt(self):
        skills = load_tool_skills()
        for name, skill in skills.items():
            self.assertTrue(skill.prompt, f"Skill {name} has empty prompt")


class TestSkillSelection(unittest.TestCase):

    def setUp(self):
        clear_cache()

    def test_error_recovery(self):
        messages = [
            {"role": "tool", "name": "Edit", "content": "Error: old_string not found"},
        ]
        result = _find_last_failed_tool(messages)
        self.assertEqual(result, "Edit")

    def test_no_error(self):
        messages = [
            {"role": "tool", "name": "Read", "content": "1\thello world"},
        ]
        result = _find_last_failed_tool(messages)
        self.assertIsNone(result)

    def test_recent_tools(self):
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"name": "Read", "input": {}, "id": "1"},
                {"name": "Glob", "input": {}, "id": "2"},
            ]},
            {"role": "assistant", "content": "", "tool_calls": [
                {"name": "Edit", "input": {}, "id": "3"},
            ]},
        ]
        recent = _get_recent_tools(messages, n=2)
        self.assertIn("Edit", recent)
        self.assertIn("Read", recent)

    def test_intent_prediction(self):
        predicted = _predict_tools({"content": "please edit the file and fix the bug"})
        self.assertIn("Edit", predicted)

    def test_inject_skills(self):
        messages = [
            {"role": "user", "content": "edit the config file"},
        ]
        config = {"skill_token_budget": 500}
        result = select_and_inject_skills("Base system prompt", messages, [], config)
        self.assertIn("Tool Usage Guidance", result)
        self.assertIn("Edit", result)

    def test_no_injection_zero_budget(self):
        messages = [{"role": "user", "content": "edit something"}]
        config = {"skill_token_budget": 0}
        result = select_and_inject_skills("Base", messages, [], config)
        self.assertEqual(result, "Base")


class TestPredictTools(unittest.TestCase):

    def test_search_keywords(self):
        self.assertIn("Grep", _predict_tools({"content": "search for the function"}))
        self.assertIn("Glob", _predict_tools({"content": "find all python files"}))

    def test_write_keywords(self):
        self.assertIn("Write", _predict_tools({"content": "create a new file"}))

    def test_run_keywords(self):
        self.assertIn("Bash", _predict_tools({"content": "run the tests"}))


if __name__ == "__main__":
    unittest.main()
