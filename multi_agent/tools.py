"""Multi-agent tool registrations.

Registers the following tools into the central tool_registry:
  Agent            — spawn a sub-agent (sync or background)
  SendMessage      — send a message to a named background agent
  CheckAgentResult — check status/result of a background agent
  ListAgentTasks   — list all active/finished agent tasks
  ListAgentTypes   — list available agent type definitions
"""
from __future__ import annotations

from tool_registry import ToolDef, register_tool
from .subagent import SubAgentManager, get_agent_definition, load_agent_definitions


# ── Singleton manager ──────────────────────────────────────────────────────

_agent_manager: SubAgentManager | None = None


def get_agent_manager() -> SubAgentManager:
    """Return (and lazily create) the process-wide SubAgentManager."""
    global _agent_manager
    if _agent_manager is None:
        _agent_manager = SubAgentManager()
    return _agent_manager


# ── Tool implementations ───────────────────────────────────────────────────

def _agent_tool(params: dict, config: dict) -> str:
    """Spawn a sub-agent.

    Reads from config:
      _system_prompt  — injected by agent.py run(), used as base system prompt
      _depth          — current nesting depth (prevents infinite recursion)
    """
    mgr = get_agent_manager()

    prompt = params["prompt"]
    wait = params.get("wait", True)
    isolation = params.get("isolation", "")
    name = params.get("name", "")
    model_override = params.get("model", "")
    subagent_type = params.get("subagent_type", "")

    system_prompt = config.get("_system_prompt", "You are a helpful assistant.")
    depth = config.get("_depth", 0)

    # Strip private keys before passing to sub-agent
    eff_config = {k: v for k, v in config.items() if not k.startswith("_")}
    if model_override:
        eff_config["model"] = model_override

    # Resolve agent definition
    agent_def = None
    if subagent_type:
        agent_def = get_agent_definition(subagent_type)
        if agent_def is None:
            return (
                f"Error: unknown subagent_type '{subagent_type}'. "
                "Use ListAgentTypes to see available types."
            )

    task = mgr.spawn(
        prompt, eff_config, system_prompt,
        depth=depth,
        agent_def=agent_def,
        isolation=isolation,
        name=name,
    )

    if task.status == "failed":
        return f"Error spawning agent: {task.result}"

    if wait:
        mgr.wait(task.id, timeout=300)
        result = task.result or f"(no output — status: {task.status})"
        header = f"[Agent: {task.name}"
        if subagent_type:
            header += f" ({subagent_type})"
        if task.worktree_branch:
            header += f", branch: {task.worktree_branch}"
        header += "]"
        return f"{header}\n\n{result}"
    else:
        info_parts = [f"Task ID: {task.id}", f"Name: {task.name}", f"Status: {task.status}"]
        if subagent_type:
            info_parts.append(f"Type: {subagent_type}")
        if task.worktree_branch:
            info_parts.append(f"Worktree branch: {task.worktree_branch}")
        info_parts.append("Use CheckAgentResult or SendMessage to interact with this agent.")
        return "\n".join(info_parts)


def _send_message(params: dict, config: dict) -> str:
    mgr = get_agent_manager()
    target = params["to"]
    message = params["message"]
    ok = mgr.send_message(target, message)
    if ok:
        return f"Message queued for agent '{target}'. It will be processed after current work completes."
    task_id = mgr._by_name.get(target, target)
    task = mgr.tasks.get(task_id)
    if task is None:
        return f"Error: no agent found with id or name '{target}'"
    return f"Error: agent '{target}' is not running (status: {task.status}). Cannot send message."


def _check_agent_result(params: dict, config: dict) -> str:
    mgr = get_agent_manager()
    task_id = params["task_id"]
    task = mgr.tasks.get(task_id)
    if task is None:
        return f"Error: no task with id '{task_id}'"
    lines = [f"Status: {task.status}", f"Name: {task.name}"]
    if task.worktree_branch:
        lines.append(f"Worktree branch: {task.worktree_branch}")
    if task.result:
        lines.append(f"\nResult:\n{task.result}")
    return "\n".join(lines)


def _list_agent_tasks(params: dict, config: dict) -> str:
    mgr = get_agent_manager()
    tasks = mgr.list_tasks()
    if not tasks:
        return "No sub-agent tasks."
    lines = ["ID           | Name     | Status    | Worktree branch | Prompt"]
    lines.append("-------------|----------|-----------|-----------------|------")
    for t in tasks:
        prompt_short = t.prompt[:50] + ("..." if len(t.prompt) > 50 else "")
        wt = t.worktree_branch[:15] if t.worktree_branch else "-"
        lines.append(f"{t.id} | {t.name[:8]:8s} | {t.status:9s} | {wt:15s} | {prompt_short}")
    return "\n".join(lines)


def _list_agent_types(params: dict, config: dict) -> str:
    defs = load_agent_definitions()
    if not defs:
        return "No agent types available."
    lines = ["Available agent types:", ""]
    for aname, d in sorted(defs.items()):
        model_info = f"  model: {d.model}" if d.model else ""
        tools_info = f"  tools: {', '.join(d.tools)}" if d.tools else ""
        lines.append(f"  {aname:20s}  [{d.source:8s}]  {d.description}")
        if model_info:
            lines.append(f"                           {model_info}")
        if tools_info:
            lines.append(f"                           {tools_info}")
    lines.append("")
    lines.append(
        "Create custom agents: place .md files in ~/.little-coder/agents/ or .little-coder/agents/"
    )
    return "\n".join(lines)


# ── Tool registrations ─────────────────────────────────────────────────────

register_tool(ToolDef(
    name="Agent",
    schema={
        "name": "Agent",
        "description": (
            "Spawn a sub-agent to handle a task autonomously. The sub-agent runs in a "
            "separate thread with its own conversation history. Supports specialized agent "
            "types (coder, reviewer, researcher, tester, or custom from .little-coder/agents/), "
            "isolated git worktrees for parallel work, and background execution.\n\n"
            "When using isolation='worktree', the agent gets its own git branch and "
            "working copy — ideal for parallel coding tasks that shouldn't interfere."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Task description for the sub-agent",
                },
                "subagent_type": {
                    "type": "string",
                    "description": (
                        "Specialized agent type: 'general-purpose', 'coder', 'reviewer', "
                        "'researcher', 'tester', or any custom type. "
                        "Use ListAgentTypes to see all available types."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Human-readable name for this agent instance. "
                        "Makes it addressable via SendMessage while running in background."
                    ),
                },
                "model": {
                    "type": "string",
                    "description": "Model override for this specific agent (optional)",
                },
                "wait": {
                    "type": "boolean",
                    "description": (
                        "Block until complete (default: true). "
                        "Set false to run in background."
                    ),
                },
                "isolation": {
                    "type": "string",
                    "enum": ["worktree"],
                    "description": (
                        "'worktree' creates a temporary git worktree so the agent works "
                        "on an isolated copy of the repo. Changes stay on a separate branch "
                        "and can be reviewed/merged after completion."
                    ),
                },
            },
            "required": ["prompt"],
        },
    },
    func=_agent_tool,
    read_only=False,
    concurrent_safe=False,
))

register_tool(ToolDef(
    name="SendMessage",
    schema={
        "name": "SendMessage",
        "description": (
            "Send a follow-up message to a running background agent. "
            "The message is queued and processed after the agent finishes its current work. "
            "Reference agents by the name set via Agent(name=...) or by task ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to":      {"type": "string", "description": "Agent name or task ID"},
                "message": {"type": "string", "description": "Message to send to the agent"},
            },
            "required": ["to", "message"],
        },
    },
    func=_send_message,
    read_only=False,
    concurrent_safe=True,
))

register_tool(ToolDef(
    name="CheckAgentResult",
    schema={
        "name": "CheckAgentResult",
        "description": "Check the status and result of a spawned sub-agent task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID returned by Agent tool"},
            },
            "required": ["task_id"],
        },
    },
    func=_check_agent_result,
    read_only=True,
    concurrent_safe=True,
))

register_tool(ToolDef(
    name="ListAgentTasks",
    schema={
        "name": "ListAgentTasks",
        "description": "List all sub-agent tasks and their statuses.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    func=_list_agent_tasks,
    read_only=True,
    concurrent_safe=True,
))

register_tool(ToolDef(
    name="ListAgentTypes",
    schema={
        "name": "ListAgentTypes",
        "description": (
            "List all available agent types (built-in and custom). "
            "Use the type names as subagent_type when calling Agent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    func=_list_agent_types,
    read_only=True,
    concurrent_safe=True,
))
