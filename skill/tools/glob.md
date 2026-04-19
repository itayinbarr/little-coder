---
name: glob-guidance
type: tool-guidance
target_tool: Glob
priority: 8
token_cost: 80
user-invocable: false
---
## Glob Tool
Find files matching a glob pattern.

REQUIRED: pattern (glob pattern like "**/*.py")
OPTIONAL: path (directory to search in, defaults to cwd)

RULES:
- Use ** for recursive matching across directories
- Returns sorted list of matching file paths
- Good for finding files by extension or name pattern

EXAMPLE:
```tool
{"name": "Glob", "input": {"pattern": "**/*.py"}}
```

EXAMPLE with path:
```tool
{"name": "Glob", "input": {"pattern": "*.md", "path": "/path/to/docs/"}}
```
