---
name: grep-guidance
type: tool-guidance
target_tool: Grep
priority: 8
token_cost: 100
user-invocable: false
---
## Grep Tool
Search file contents with regex. Uses ripgrep.

REQUIRED: pattern (regex pattern)
OPTIONAL: path (directory/file), include (file glob filter like "*.py"), max_results (limit)

RULES:
- Supports full regex syntax
- Use include to filter by file type (e.g. "*.py", "*.js")
- Returns matching lines with file path and line number
- Good for finding function definitions, imports, references

EXAMPLE:
```tool
{"name": "Grep", "input": {"pattern": "def main", "include": "*.py"}}
```

EXAMPLE with path:
```tool
{"name": "Grep", "input": {"pattern": "TODO|FIXME", "path": "/path/to/project/"}}
```
