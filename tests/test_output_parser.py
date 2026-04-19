"""Tests for local/output_parser.py — JSON repair and tool-call validation."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from local.output_parser import repair_json, parse_tool_call, parse_text_tool_calls, inject_tool_instructions


class TestRepairJSON(unittest.TestCase):

    def test_valid_json(self):
        self.assertEqual(repair_json('{"a": 1}'), {"a": 1})

    def test_trailing_comma(self):
        self.assertEqual(repair_json('{"a": 1, }'), {"a": 1})

    def test_trailing_comma_array(self):
        self.assertEqual(repair_json('[1, 2, ]'), [1, 2])

    def test_single_quotes(self):
        result = repair_json("{'name': 'Read'}")
        self.assertEqual(result.get("name"), "Read")

    def test_unquoted_keys(self):
        result = repair_json('{name: "Read", path: "/tmp"}')
        self.assertEqual(result.get("name"), "Read")
        self.assertEqual(result.get("path"), "/tmp")

    def test_missing_closing_brace(self):
        result = repair_json('{"name": "Read"')
        self.assertEqual(result.get("name"), "Read")

    def test_empty_string(self):
        self.assertEqual(repair_json(""), {})

    def test_garbage(self):
        result = repair_json("not json at all")
        self.assertIn("_raw", result)

    def test_nested_json_extraction(self):
        result = repair_json('Some text {"name": "Edit"} more text')
        self.assertEqual(result.get("name"), "Edit")


class TestParseToolCall(unittest.TestCase):

    def setUp(self):
        self.schema = {
            "name": "Edit",
            "description": "Edit a file",
            "input_schema": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                },
                "required": ["file_path", "old_string", "new_string"],
            },
        }

    def test_valid_input(self):
        inp = {"file_path": "/tmp/f.py", "old_string": "a", "new_string": "b"}
        result = parse_tool_call(inp, self.schema)
        self.assertEqual(result["file_path"], "/tmp/f.py")

    def test_case_insensitive_keys(self):
        inp = {"File_Path": "/tmp/f.py", "Old_String": "a", "New_String": "b"}
        result = parse_tool_call(inp, self.schema)
        self.assertEqual(result["file_path"], "/tmp/f.py")

    def test_boolean_coercion(self):
        inp = {"file_path": "/f", "old_string": "a", "new_string": "b", "replace_all": "true"}
        result = parse_tool_call(inp, self.schema)
        self.assertTrue(result["replace_all"])

    def test_no_schema(self):
        inp = {"a": 1}
        self.assertEqual(parse_tool_call(inp, None), inp)


class TestParseTextToolCalls(unittest.TestCase):

    def test_tool_block(self):
        text = 'Here is my plan:\n```tool\n{"name": "Read", "input": {"file_path": "/tmp/f"}}\n```'
        calls = parse_text_tool_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "Read")
        self.assertEqual(calls[0]["input"]["file_path"], "/tmp/f")

    def test_xml_style(self):
        text = '<tool_call>\n{"name": "Bash", "input": {"command": "ls"}}\n</tool_call>'
        calls = parse_text_tool_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "Bash")

    def test_multiple_blocks(self):
        text = (
            '```tool\n{"name": "Read", "input": {"file_path": "/a"}}\n```\n'
            'Then:\n```tool\n{"name": "Edit", "input": {"file_path": "/a", "old_string": "x", "new_string": "y"}}\n```'
        )
        calls = parse_text_tool_calls(text)
        self.assertEqual(len(calls), 2)

    def test_no_tool_calls(self):
        calls = parse_text_tool_calls("Just some regular text")
        self.assertEqual(len(calls), 0)


class TestInjectToolInstructions(unittest.TestCase):

    def test_injects_tool_info(self):
        schemas = [{"name": "Read", "description": "Read file",
                     "input_schema": {"properties": {"file_path": {"type": "string", "description": "path"}},
                                      "required": ["file_path"]}}]
        result = inject_tool_instructions("Base system", schemas)
        self.assertIn("Read", result)
        self.assertIn("```tool", result)
        self.assertIn("file_path", result)


if __name__ == "__main__":
    unittest.main()
