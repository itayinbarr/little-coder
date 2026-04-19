"""Tests for local/quality.py — response quality monitoring."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from local.quality import assess_response, build_correction_message


class TestAssessResponse(unittest.TestCase):

    def test_valid_response_text_only(self):
        ok, reason = assess_response("Here is the answer", [], [])
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_empty_response(self):
        ok, reason = assess_response("", [], [])
        self.assertFalse(ok)
        self.assertEqual(reason, "empty_response")

    def test_unknown_tool(self):
        # Register a dummy tool so the registry is populated
        from tool_registry import register_tool, ToolDef, clear_registry
        register_tool(ToolDef("Read", {}, lambda p, c: "", True, True))
        try:
            ok, reason = assess_response("", [{"name": "FakeTool123", "input": {}}], [])
            self.assertFalse(ok)
            self.assertTrue(reason.startswith("unknown_tool"))
        finally:
            clear_registry()

    def test_repeated_tool_call(self):
        # Need >= 2 messages in history for repeated check
        messages = [
            {"role": "user", "content": "do something"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"name": "Read", "input": {"file_path": "/tmp/f"}}
            ]},
        ]
        tool_calls = [{"name": "Read", "input": {"file_path": "/tmp/f"}}]
        ok, reason = assess_response("", tool_calls, messages)
        self.assertFalse(ok)
        self.assertEqual(reason, "repeated_tool_call")

    def test_malformed_args(self):
        tool_calls = [{"name": "Read", "input": {"_raw": "broken json"}}]
        ok, reason = assess_response("", tool_calls, [])
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("malformed_args"))


class TestBuildCorrectionMessage(unittest.TestCase):

    def test_empty_response(self):
        msg = build_correction_message("empty_response")
        self.assertIn("empty", msg.lower())

    def test_unknown_tool(self):
        msg = build_correction_message("unknown_tool:FakeTool")
        self.assertIn("FakeTool", msg)
        self.assertIn("does not exist", msg)

    def test_repeated_tool(self):
        msg = build_correction_message("repeated_tool_call")
        self.assertIn("same tool call", msg)


if __name__ == "__main__":
    unittest.main()
