---
name: edit-guidance
type: tool-guidance
target_tool: edit
priority: 10
token_cost: 150
user-invocable: false
---
## `edit` Tool
Replace exact text in a file. This is the **default tool for changing any existing file** — prefer it over `write` for anything except creating a new file from scratch.

REQUIRED: path (absolute), edits (array of {oldText, newText})
OPTIONAL: none

RULES:
- Each `oldText` must match EXACTLY (whitespace, indentation, line endings all matter)
- Each `oldText` must be unique in the file — include 2-3 lines of surrounding context if needed
- `edits` is matched against the **original** file, not after earlier edits apply — do not overlap or nest
- To delete text: set `newText` to ""
- Use `read` first if you do not already have the file's current content
- Batch multiple disjoint changes in one call by passing multiple `edits[]` entries

EXAMPLE (single change):
```tool
{"name": "edit", "input": {"path": "/absolute/path/file.py", "edits": [{"oldText": "def hello():\n    return 1", "newText": "def hello():\n    return 2"}]}}
```

EXAMPLE (two changes in one call):
```tool
{"name": "edit", "input": {"path": "/absolute/path/file.py", "edits": [{"oldText": "MAX = 10", "newText": "MAX = 20"}, {"oldText": "TIMEOUT = 5", "newText": "TIMEOUT = 30"}]}}
```

RECOVERY WHEN `edit` FAILS:
- "String not found" → use `read` to get the exact current content (whitespace often differs), then retry `edit` with the exact string
- "Found multiple times" → include more surrounding context so `oldText` is unique, then retry `edit`
- Do NOT fall back to `write` just because `edit` failed once — re-read, fix `oldText`, retry. `write` is almost always the wrong recovery here for an existing file.
