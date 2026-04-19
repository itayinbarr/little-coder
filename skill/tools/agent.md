---
name: agent-guidance
type: tool-guidance
target_tool: Agent
priority: 6
token_cost: 120
user-invocable: false
---
## Agent Tool
Spawn a sub-agent to handle a task autonomously.

REQUIRED: prompt (task description for the sub-agent)
OPTIONAL: subagent_type (coder/reviewer/researcher/tester/general-purpose), name (for messaging), isolation ("worktree" for git isolation)

RULES:
- Use for independent tasks that don't need your direct attention
- Sub-agents get their own context and can use all tools
- Use subagent_type to get specialized behavior
- Use isolation="worktree" when the agent needs to modify files independently

EXAMPLE:
```tool
{"name": "Agent", "input": {"prompt": "Find all Python files that import requests and list them", "subagent_type": "researcher"}}
```
