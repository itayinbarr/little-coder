"""Tests for local/config.py — model profiles and detection."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from local.config import is_small_model, get_model_profile


class TestIsSmallModel(unittest.TestCase):

    def test_claude_is_large(self):
        self.assertFalse(is_small_model("claude-opus-4-6"))
        self.assertFalse(is_small_model("claude-sonnet-4-6"))

    def test_gpt_is_large(self):
        self.assertFalse(is_small_model("gpt-4o"))
        self.assertFalse(is_small_model("gpt-4-turbo"))

    def test_gemini_is_large(self):
        self.assertFalse(is_small_model("gemini-2.0-flash"))

    def test_ollama_gemma_is_small(self):
        self.assertTrue(is_small_model("gemma3:4b"))
        self.assertTrue(is_small_model("ollama/gemma3:4b"))

    def test_llama_is_small(self):
        self.assertTrue(is_small_model("llama3.2:3b"))
        self.assertTrue(is_small_model("ollama/llama3.2:1b"))

    def test_qwen_small_is_small(self):
        self.assertTrue(is_small_model("qwen2.5:3b"))

    def test_phi_is_small(self):
        self.assertTrue(is_small_model("phi4-mini"))


class TestGetModelProfile(unittest.TestCase):

    def test_exact_match(self):
        profile = get_model_profile("gemma3:4b")
        self.assertEqual(profile["context_limit"], 8192)
        self.assertEqual(profile["max_retries"], 2)

    def test_large_model_profile(self):
        profile = get_model_profile("claude-opus-4-6")
        self.assertEqual(profile["context_limit"], 128000)
        self.assertEqual(profile["max_retries"], 0)

    def test_with_provider_prefix(self):
        profile = get_model_profile("ollama/gemma3:4b")
        self.assertEqual(profile["context_limit"], 8192)

    def test_unknown_small_model(self):
        profile = get_model_profile("some-random-model:2b")
        # Should get default small profile
        self.assertEqual(profile["context_limit"], 8192)

    def test_family_match(self):
        profile = get_model_profile("gemma3:4b-instruct-q4")
        # Should match gemma3:4b profile
        self.assertEqual(profile["context_limit"], 8192)


if __name__ == "__main__":
    unittest.main()
