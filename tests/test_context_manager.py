"""Tests for local/context_manager.py — system prompt compression and message pruning."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from local.context_manager import (
    estimate_tokens, compress_system_prompt, prune_messages,
)


class TestEstimateTokens(unittest.TestCase):

    def test_basic(self):
        # ~3.5 chars per token
        self.assertAlmostEqual(estimate_tokens("a" * 350), 100, delta=5)

    def test_empty(self):
        self.assertEqual(estimate_tokens(""), 1)


class TestCompressSystemPrompt(unittest.TestCase):

    def test_no_compression_needed(self):
        prompt = "Short prompt"
        result = compress_system_prompt(prompt, 1000)
        self.assertEqual(result, prompt)

    def test_compression_strips_sections(self):
        prompt = (
            "# Identity\nYou are an AI assistant.\n"
            "## Windows Shell Hints\nLong windows hints here...\n" * 10
            + "## Multi-Agent Guidelines\nLong guidelines...\n" * 10
            + "# Core Rules\nBe helpful.\n"
        )
        result = compress_system_prompt(prompt, 100)
        self.assertLess(estimate_tokens(result), 110)  # within budget + tolerance

    def test_zero_budget_no_compression(self):
        prompt = "Some prompt"
        result = compress_system_prompt(prompt, 0)
        self.assertEqual(result, prompt)


class TestPruneMessages(unittest.TestCase):

    def test_short_conversation(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = prune_messages(messages, 8192)
        self.assertEqual(len(result), 2)

    def test_long_conversation_pruned(self):
        messages = []
        for i in range(20):
            messages.append({"role": "user", "content": f"message {i} " * 100})
            messages.append({"role": "assistant", "content": f"response {i} " * 100})

        result = prune_messages(messages, 2048)
        self.assertLess(len(result), len(messages))
        # Should always keep the last 4
        self.assertEqual(result[-1], messages[-1])

    def test_empty_messages(self):
        self.assertEqual(prune_messages([], 8192), [])

    def test_very_small_context(self):
        messages = [
            {"role": "user", "content": "a" * 1000},
            {"role": "assistant", "content": "b" * 1000},
            {"role": "user", "content": "c" * 1000},
            {"role": "assistant", "content": "d" * 1000},
        ]
        result = prune_messages(messages, 1024, reserved_for_generation=512)
        self.assertLessEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
