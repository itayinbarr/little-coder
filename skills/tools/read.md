---
name: read-guidance
type: tool-guidance
target_tool: read
priority: 10
token_cost: 100
user-invocable: false
---
## `read` Tool
Read a file's contents with line numbers using `read`.

REQUIRED: path (absolute path)
OPTIONAL: limit (max lines), offset (start line, 0-indexed)

RULES:
- Always use absolute paths, never relative
- Use limit+offset for large files (read in chunks of 100-200 lines)
- Returns format: "N\tline_content" (tab-separated line number + content)

EXAMPLE:
```tool
{"name": "read", "input": {"path": "/absolute/path/to/file.py"}}
```

EXAMPLE with range:
```tool
{"name": "read", "input": {"path": "/absolute/path/to/file.py", "limit": 50, "offset": 100}}
```
