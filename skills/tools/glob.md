---
name: glob-guidance
type: tool-guidance
target_tool: glob
priority: 8
token_cost: 80
user-invocable: false
---
## `glob` Tool
Find files matching a glob pattern.

REQUIRED: pattern (glob pattern like "**/*.py")
OPTIONAL: path (directory to search in, defaults to cwd)

RULES:
- Use ** for recursive matching across directories
- Returns sorted list of matching file paths
- Good for finding files by extension or name pattern

EXAMPLE:
```tool
{"name": "glob", "input": {"pattern": "**/*.py"}}
```

EXAMPLE with path:
```tool
{"name": "glob", "input": {"pattern": "*.md", "path": "/path/to/docs/"}}
```
