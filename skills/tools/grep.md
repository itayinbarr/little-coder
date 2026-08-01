---
name: grep-guidance
type: tool-guidance
target_tool: grep
priority: 8
token_cost: 100
user-invocable: false
---
## `grep` Tool
Search file contents with regex. Uses ripgrep.

REQUIRED: pattern (regex pattern)
OPTIONAL: path (directory/file), glob (file glob filter like "*.py"), ignoreCase (bool), literal (bool — treat pattern as literal text), context (lines of context before/after), limit (max matches, default 100)

RULES:
- Supports full regex syntax (unless `literal: true`)
- Use `glob` to filter by file type (e.g. "*.py", "*.js")
- Use `limit` to cap results; default 100
- Returns matching lines with file path and line number
- Good for finding function definitions, imports, references

EXAMPLE:
```tool
{"name": "grep", "input": {"pattern": "def main", "glob": "*.py"}}
```

EXAMPLE with path:
```tool
{"name": "grep", "input": {"pattern": "TODO|FIXME", "path": "/path/to/project/"}}
```
