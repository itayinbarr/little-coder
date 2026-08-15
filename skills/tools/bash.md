---
name: bash-guidance
type: tool-guidance
target_tool: bash
priority: 10
token_cost: 120
user-invocable: false
---
## `bash` Tool
Execute a shell command and return stdout+stderr.

REQUIRED: command (shell command string)
OPTIONAL: timeout (seconds, default 30 - use 120-300 for installs/builds)

RULES:
- Stateless: each call starts fresh (cd does not persist)
- Use absolute paths or chain with && (e.g. "cd /path && make")
- Use timeout=120 for: pip install, npm install, builds, downloads
- Returns combined stdout and stderr

EXAMPLE:
```tool
{"name": "bash", "input": {"command": "ls -la /path/to/project/"}}
```

EXAMPLE with timeout:
```tool
{"name": "bash", "input": {"command": "pip install requests", "timeout": 120}}
```
