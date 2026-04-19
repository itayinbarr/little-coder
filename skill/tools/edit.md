---
name: edit-guidance
type: tool-guidance
target_tool: Edit
priority: 10
token_cost: 150
user-invocable: false
---
## Edit Tool
Replace exact text in a file. This is the **default tool for changing any existing file** — prefer it over Write for anything except creating a new file from scratch.

REQUIRED: file_path (absolute), old_string (exact text to find), new_string (replacement)
OPTIONAL: replace_all (boolean, replace all occurrences)

RULES:
- old_string must match EXACTLY (whitespace, indentation, line endings all matter)
- old_string must appear exactly ONCE unless replace_all=true
- Include enough surrounding context (2-3 lines) to make old_string unique
- To delete text: set new_string to ""
- Read the file first if you do not already have its current content

EXAMPLE:
```tool
{"name": "Edit", "input": {"file_path": "/absolute/path/file.py", "old_string": "def hello():\n    return 1", "new_string": "def hello():\n    return 2"}}
```

RECOVERY WHEN Edit FAILS:
- "String not found" → Read the file to get the exact current content (whitespace often differs), then retry Edit with the exact string
- "Found multiple times" → include more surrounding context so old_string is unique, then retry Edit
- Do NOT fall back to Write just because Edit failed once — re-read, fix old_string, retry. Write is almost always the wrong recovery here for an existing file.
